import streamlit as st
import random

# 페이지 설정 (가장 먼저 호출되어야 함)
st.set_page_config(page_title="학교 생활 도우미", page_icon="🏫", layout="centered")

import pandas as pd
import requests
import json
import io
from datetime import datetime, timedelta
from workalendar.asia import SouthKorea
import re  # 정규 표현식 사용을 위해 추가
import base64
import time
import os
import uuid
import tempfile
import logging

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('전학공앱')
logger.setLevel(logging.INFO)

# Firebase 관련 라이브러리 조건부 임포트
firebase_available = False
firebase = None
db = None

try:
    import firebase_admin
    from firebase_admin import credentials, db as firebase_rtdb, storage

    # Streamlit secrets에서 직접 dictionary 형태로 자격 증명을 로드
    if "firebase" in st.secrets:
        try:
            # st.secrets는 dict-like 객체를 반환하므로 dict()로 변환하여 사용
            cred_dict = dict(st.secrets["firebase"]["service_account_key"])
            database_url = st.secrets["firebase"]["database_url"]
            # 스토리지 버킷 URL (하드코딩)
            storage_bucket = "project-a019a.firebasestorage.app"

            # placeholder 값인지 확인
            if "your-project-id" in cred_dict.get("project_id", ""):
                st.sidebar.warning("Firebase 서비스 계정 키가 .streamlit/secrets.toml 파일에 설정되지 않았습니다.")
            else:
                # private_key의 "\\n"을 실제 줄바꿈 문자로 변경하여 확실하게 처리
                cred_dict['private_key'] = cred_dict['private_key'].replace('\\\\n', '\\n')
                cred = credentials.Certificate(cred_dict)
                
                if not firebase_admin._apps:
                    firebase_admin.initialize_app(cred, {
                        'databaseURL': database_url,
                        'storageBucket': storage_bucket
                    })
                
                # Store bucket name globally for later use
                global STORAGE_BUCKET_NAME
                STORAGE_BUCKET_NAME = storage_bucket
                
                # Firebase 연결 성공 - 전역 변수 설정
                firebase_available = True
                db = firebase_rtdb

        except Exception as e:
            st.sidebar.error(f"Firebase Admin SDK 초기화 실패: {e}")
            st.sidebar.warning("올바른 서비스 계정 키와 Database URL을 .streamlit/secrets.toml 파일에 설정하세요.")
    else:
        st.sidebar.warning(".streamlit/secrets.toml 파일에 Firebase 설정이 없습니다.")

except ImportError as e:
    st.sidebar.warning(f"Firebase Admin SDK 로드 실패: {e}")
    st.sidebar.warning("협업 기능을 사용하려면 'pip install firebase-admin' 명령어를 실행하세요.")

# INSERT_YOUR_REWRITE_HERE

# 사용자 세션 ID 초기화 (URL 파라미터 기반 영구 유지)
if 'session_id' not in st.session_state:
    # URL에 user_id가 있는지 확인
    query_params = st.query_params
    if 'user_id' in query_params:
        st.session_state.session_id = query_params['user_id']
    else:
        # 없으면 새로 생성하고 URL에 저장
        new_user_id = f"user_{int(time.time())}_{random.randint(1000, 9999)}"
        st.session_state.session_id = new_user_id
        st.query_params['user_id'] = new_user_id

if 'work_session_id' not in st.session_state:
    st.session_state.work_session_id = f"session_{int(time.time())}"
    
if 'school_dataframes' not in st.session_state:
    st.session_state.school_dataframes = {}
    
if 'school_vacations' not in st.session_state:
    st.session_state.school_vacations = {}
    
if 'school_excluded_dates' not in st.session_state:
    st.session_state.school_excluded_dates = {}

# 작업 흐름 제어를 위한 세션 상태 초기화
if 'processing_step' not in st.session_state:
    st.session_state.processing_step = 'start'  # 'start', 'converting', 'results'
    
# 학교 목록 초기화 (비어있는 목록으로 시작)
if 'school_list' not in st.session_state:
    st.session_state.school_list = []
    
# 학교 코드 초기화
if 'school_code' not in st.session_state:
    st.session_state.school_code = None

# 협업 방 관련 상태
if 'room_id' not in st.session_state:
    # URL에서 room_id 복원 시도
    query_params = st.query_params
    if 'room_id' in query_params:
        st.session_state.room_id = query_params['room_id']
    else:
        st.session_state.room_id = None
if 'room_required_count' not in st.session_state:
    st.session_state.room_required_count = 0
if 'room_name' not in st.session_state:
    st.session_state.room_name = None

# URL 파라미터 변경 시 세션 상태 업데이트 (사용자가 URL을 공유받아 들어온 경우)
current_query_params = st.query_params
if 'user_id' in current_query_params and st.session_state.session_id != current_query_params['user_id']:
    st.session_state.session_id = current_query_params['user_id']


# 사용자 상태 업데이트 함수
def update_user_status(status="online"):
    global firebase_available  # global 선언을 함수 시작 부분에 배치
    
    if firebase_available:
        try:
            # 방에 참여 중이면 방 참여자 상태 업데이트, 아니면 전역 세션 상태
            if st.session_state.room_id and st.session_state.school_code:
                user_path = f"rooms/{st.session_state.school_code}/{st.session_state.room_id}/participants/{st.session_state.session_id}"
                db.reference(user_path).update({
                    "last_seen": int(time.time()),
                    "status": status
                })
            else:
                user_path = f"sessions/{st.session_state.work_session_id}/users/{st.session_state.session_id}"
                db.reference(user_path).update({
                    "last_seen": int(time.time()),
                    "status": status
                })
        except Exception as e:
            st.sidebar.error(f"사용자 상태 업데이트 실패: {e}")
            st.sidebar.warning("Firebase 데이터베이스 보안 규칙을 확인하세요.")
            firebase_available = False

# 사용자가 페이지를 나갈 때 상태 업데이트
def on_user_exit():
    global firebase_available
    
    if firebase_available:
        try:
            update_user_status("offline")
        except Exception as e:
            # 종료 시에는 오류 메시지를 표시하지 않음
            firebase_available = False

# 활성 사용자 가져오기
def get_active_users():
    if firebase_available:
        try:
            # 방에 참여 중이면 방 참여자 수
            if st.session_state.room_id and st.session_state.school_code:
                users_path = f"rooms/{st.session_state.school_code}/{st.session_state.room_id}/participants"
            else:
                users_path = f"sessions/{st.session_state.work_session_id}/users"
                
            users = db.reference(users_path).get()
            active_users = []

            if users:
                for user_id, user_data in users.items():
                    # 마지막 활동이 3분 이내인 사용자만 활성 상태로 간주
                    if user_data.get("last_seen", 0) > (time.time() - 180):
                        active_users.append(user_id)

            return len(active_users)
        except Exception as e:
            # 오류 발생 시 조용히 기본값 반환
            return 1
    return 1  # Firebase 사용 불가 시 기본값 1 반환

# 업로드된 파일 저장 함수 (Storage 사용)
def save_uploaded_file(uploaded_file, school_code, school_name):
    """
    업로드된 파일 저장 및 Firebase Storage/Database에 업로드
    """
    logging.info(f"파일 처리 시작: {uploaded_file.name}")
    
    # 로컬 저장 디렉토리 생성
    save_folder = os.path.join("uploads", school_code)
    os.makedirs(save_folder, exist_ok=True)
    
    # 저장 경로
    save_path = os.path.join(save_folder, uploaded_file.name)
    
    # 로컬 파일 저장
    with open(save_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    
    logging.info(f"로컬 파일 저장 완료: {save_path}")
    
    # Firebase 업로드 시도
    firebase_upload_success = False
    if firebase_available and db is not None:
        try:
            # 1. 파일 데이터 분석 (메타데이터용)
            file_ext = os.path.splitext(uploaded_file.name)[1].lower()
            if file_ext in ['.xlsx', '.xls']:
                df = pd.read_excel(save_path)
            elif file_ext == '.csv':
                df = pd.read_csv(save_path)
            else:
                # 분석하지 않고 계속 진행
                df = pd.DataFrame()
            
            # 날짜 형식으로 추정되는 컬럼 추출
            date_columns = []
            if not df.empty:
                for col in df.columns:
                    if '날짜' in str(col) or 'date' in str(col).lower() or '일자' in str(col):
                        date_columns.append(col)
            
            # 2. Firebase Storage에 파일 업로드
            bucket = storage.bucket()
            room_id_path = st.session_state.get("room_id", "common")
            blob_path = f"uploads/{school_code}/{room_id_path}/{uploaded_file.name}" # 방 별로 경로 분리
            blob = bucket.blob(blob_path)
            
            # 메타데이터 설정
            blob.metadata = {
                "upload_user": st.session_state.session_id,
                "school_name": school_name,
                "original_filename": uploaded_file.name,
                "room_id": st.session_state.get("room_id")
            }
            
            blob.upload_from_filename(save_path)
            logging.info(f"Firebase Storage 업로드 성공: {blob_path}")
            
            # 3. Realtime Database에 메타데이터 저장
            file_metadata = {
                "filename": uploaded_file.name,
                "upload_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "upload_user": st.session_state.session_id,
                "storage_path": blob_path,  # 스토리지 경로 저장
                "column_names": list(df.columns) if not df.empty else [],
                "row_count": len(df) if not df.empty else 0,
                "date_columns": date_columns,
                "school_name": school_name,
                "room_id": st.session_state.get("room_id"),
                "room_name": st.session_state.get("room_name"),
            }
            
            # 파일 키 생성 (특수문자 제외)
            file_key = uploaded_file.name.replace('.', '_')
            db.reference(f"file_uploads/{school_code}/{file_key}").set(file_metadata)
            
            logging.info(f"Firebase RB에 메타데이터 저장 성공: {file_key}")
            firebase_upload_success = True
            
        except Exception as e:
            logging.error(f"Firebase 업로드 실패: {e}")
            st.warning(f"파일은 로컬에 저장되었지만 클라우드 백업 중 오류 발생: {e}")
            if "storage" not in str(e).lower():
                # 스토리지 오류가 아니면 재발생시키지 않음
                pass
    
    return {
        "local_path": save_path,
        "firebase_upload": firebase_upload_success
    }

# 공유된 파일 데이터 가져오기 (Storage에서 다운로드)
def download_firebase_file(user_id, filename):
    global firebase_available
    
    if not firebase_available:
        return None
    
    try:
        school_code = st.session_state.get("school_code")
        if not school_code:
            return None
            
        # 1. 파일 메타데이터 조회
        file_key = filename.replace('.', '_')
        file_meta = db.reference(f"file_uploads/{school_code}/{file_key}").get()
        
        if not file_meta:
            # 예전 방식(session 저장) 시도
            return download_old_session_file(user_id, filename)
            
        # 2. Storage에서 다운로드
        storage_path = file_meta.get("storage_path")
        if not storage_path:
             storage_path = f"uploads/{school_code}/{filename}" # 구버전 호환
        
        # 로컬 저장 경로
        local_dir = os.path.join("uploads", school_code)
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join(local_dir, filename)
        
        # 이미 존재하면 다운로드 건너뛰기 (선택 사항)
        # if os.path.exists(local_path): ...
        
        bucket = storage.bucket()
        blob = bucket.blob(storage_path)
        
        if blob.exists():
            blob.download_to_filename(local_path)
            logging.info(f"Storage에서 파일 다운로드 완료: {local_path}")
            
            # 데이터프레임 로드
            file_ext = os.path.splitext(filename)[1].lower()
            if file_ext in ['.xlsx', '.xls']:
                return pd.read_excel(local_path)
            elif file_ext == '.csv':
                return pd.read_csv(local_path)
        else:
            st.warning(f"클라우드 저장소에서 파일 {filename}을 찾을 수 없습니다.")
            return None
            
    except Exception as e:
        st.error(f"파일 다운로드 중 오류 발생: {e}")
        return None
        
    return None

# 이전 방식 호환성 유지를 위한 함수
def download_old_session_file(user_id, filename):
    try:
        file_key = filename.replace('.', '_')
        dates_path = f"sessions/{st.session_state.work_session_id}/file_data/{user_id}/{file_key}"
        result = db.reference(dates_path).get()
        
        if result and 'dates' in result:
            date_values = result['dates']
            return pd.DataFrame({'날짜': date_values})
    except:
        pass
    return None
def reset_session():
    """Reset local Streamlit session state and optionally clear Firebase room data.
    Returns True on success, False on failure.
    """
    try:
        # Reset processing step
        st.session_state.processing_step = "start"
        # Clear stored dataframes and related info
        for key in ["school_dataframes", "school_vacations", "school_excluded_dates"]:
            if key in st.session_state:
                del st.session_state[key]
        # Clear room related session state
        st.session_state.room_id = None
        st.session_state.room_name = None
        st.session_state.room_required_count = 0
        # Optionally, you could also clear the Firebase room data here using reset_room,
        # but that would delete shared data. For a simple local reset we just clear the state.
        return True
    except Exception as e:
        st.error(f"세션 초기화 중 오류 발생: {e}")
        return False
# 모든 업로드된 파일 가져오기
def get_all_uploaded_files():
    global firebase_available
    
    if firebase_available:
        school_code = st.session_state.get("school_code")
        if not school_code:
            return []

        files_path = f"file_uploads/{school_code}"
        try:
            files_data = db.reference(files_path).get()
            
            all_files = []
            if files_data:
                # 기존 구조: file_uploads/{school}/{file_key} = metadata
                if isinstance(files_data, dict):
                    items_iter = files_data.items()
                elif isinstance(files_data, list):
                    items_iter = enumerate(files_data)
                else:
                    items_iter = []
                for file_key, file_info in items_iter:
                    if not isinstance(file_info, dict):
                        continue
                        
                    all_files.append({
                        "user_id": file_info.get("upload_user", "unknown"),
                        "file_id": file_key,
                        "filename": file_info.get("filename", "알 수 없는 파일"),
                        "upload_time": file_info.get("upload_time", 0),
                        "storage_path": file_info.get("storage_path", ""),
                        "room_id": file_info.get("room_id", None)  # room_id 추가
                    })
            
            return all_files
        except Exception as e:
            st.warning(f"파일 목록 조회 실패: {e}")
            firebase_available = False
            return []
    return []

# 세션 상태 업데이트 - 방 단위
def update_session_state(state):
    global firebase_available
    
    if firebase_available and st.session_state.room_id:
        try:
            db.reference(f"rooms/{st.session_state.school_code}/{st.session_state.room_id}/state").set(state)
        except Exception as e:
            st.warning(f"세션 상태 업데이트 실패: {e}")
            firebase_available = False

# 세션 상태 가져오기 - 방 단위
def get_session_state():
    global firebase_available
    
    if firebase_available and st.session_state.room_id:
        try:
            state = db.reference(f"rooms/{st.session_state.school_code}/{st.session_state.room_id}/state").get()
            return state if state else "start"
        except Exception as e:
            # st.warning(f"세션 상태 조회 실패: {e}") # 조용히 처리
            return "start"
    return "start"

# 협업 방/참여자 관리 유틸
def get_rooms_for_school(school_code):
    if not firebase_available or not school_code:
        return {}
    try:
        data = db.reference(f"rooms/{school_code}").get()
        return data or {}
    except Exception:
        return {}

def create_room(school_code, required_count, room_name, room_password=None):
    """
    방을 생성하고 비밀번호를 설정합니다.
    
    Args:
        school_code: 학교 코드
        required_count: 필요 인원 수
        room_name: 방 이름
        room_password: 방 비밀번호 (선택사항)
    
    Returns:
        room_id: 생성된 방 ID, 실패 시 None
    """
    if not firebase_available or not school_code:
        return None
    room_id = f"room_{int(time.time())}_{random.randint(1000, 9999)}"
    try:
        room_data = {
            "required_count": int(required_count),
            "created_at": int(time.time()),
            "created_by": st.session_state.session_id,
            "room_name": room_name or room_id,
            "state": "start"
        }
        
        # 비밀번호가 제공된 경우 해시하여 저장
        if room_password and room_password.strip():
            import hashlib
            hashed_password = hashlib.sha256(room_password.strip().encode()).hexdigest()
            room_data["password_hash"] = hashed_password
            room_data["has_password"] = True
        else:
            room_data["has_password"] = False
            
        db.reference(f"rooms/{school_code}/{room_id}").set(room_data)
        return room_id
    except Exception as e:
        logging.error(f"방 생성 실패: {e}")
        return None

def join_room(school_code, room_id):
    if not firebase_available or not school_code or not room_id:
        return False
    try:
        participants_path = f"rooms/{school_code}/{room_id}/participants/{st.session_state.session_id}"
        
        # 기존 참여자 정보 확인
        existing_participant = db.reference(participants_path).get()
        
        # 업데이트할 데이터 준비
        update_data = {
            "joined_at": existing_participant.get("joined_at", int(time.time())) if existing_participant else int(time.time()),
            "status": "online",
            "last_seen": int(time.time())
        }
        
        # 기존 참여자가 아니면 uploaded를 False로 설정
        if not existing_participant:
            update_data["uploaded"] = False
        # 기존 참여자면 uploaded 상태 유지 (업데이트하지 않음)
        
        db.reference(participants_path).update(update_data)
        
        st.session_state.work_session_id = room_id  # 기존 세션 ID를 방 ID로 사용 (호환성)
        # 방 이름 저장
        room_info = db.reference(f"rooms/{school_code}/{room_id}").get() or {}
        st.session_state.room_name = room_info.get("room_name", room_id)
        # URL에 room_id 저장
        st.query_params['room_id'] = room_id
        return True
    except Exception:
        return False

def mark_uploaded_done(school_code, room_id):
    if not firebase_available or not school_code or not room_id:
        return
    db.reference(f"rooms/{school_code}/{room_id}/participants/{st.session_state.session_id}").update({
        "uploaded": True,
        "updated_at": int(time.time())
    })

def get_room_status(school_code, room_id):
    """
    방 정보와 완료 인원/총 인원 반환
    """
    if not firebase_available or not school_code or not room_id:
        return None, 0, 0
    room_ref = db.reference(f"rooms/{school_code}/{room_id}").get() or {}
    participants = room_ref.get("participants", {}) or {}
    ready = sum(1 for p in participants.values() if p.get("uploaded"))
    total = len(participants)
    return room_ref, ready, total

def verify_room_password(school_code, room_id, password):
    """
    방 비밀번호를 확인합니다.
    
    Args:
        school_code: 학교 코드
        room_id: 방 ID
        password: 확인할 비밀번호
    
    Returns:
        True if password matches or no password set, False otherwise
    """
    if not firebase_available or not school_code or not room_id:
        return False
    
    try:
        room_info = db.reference(f"rooms/{school_code}/{room_id}").get()
        if not room_info:
            return False
        
        # 비밀번호가 설정되지 않은 방인 경우
        if not room_info.get("has_password", False):
            return True
        
        # 비밀번호 확인
        if password and password.strip():
            import hashlib
            hashed_input = hashlib.sha256(password.strip().encode()).hexdigest()
            stored_hash = room_info.get("password_hash", "")
            return hashed_input == stored_hash
        
        return False
    except Exception as e:
        logging.error(f"비밀번호 확인 실패: {e}")
        return False

# 방 초기화 (강력한 cleanup 포함)
def reset_room(school_code, room_id, password=None):
    global firebase_available
    
    if not firebase_available or not school_code or not room_id:
        return False
    
    # 비밀번호 확인
    if not verify_room_password(school_code, room_id, password):
        st.error("비밀번호가 일치하지 않습니다.")
        return False
        
    try:
        logging.info(f"방 초기화 시작: {room_id}")
        
        # 1. 스토리지 파일 삭제
        bucket = storage.bucket(name=STORAGE_BUCKET_NAME)
        # 해당 방의 폴더 전체 삭제 (uploads/{school_code}/{room_id}/...)
        prefix = f"uploads/{school_code}/{room_id}/"
        blobs = bucket.list_blobs(prefix=prefix)
        deleted_count = 0
        for blob in blobs:
            try:
                blob.delete()
                deleted_count += 1
            except Exception as e:
                logging.warning(f"Blob 삭제 실패: {blob.name} - {e}")
        
        logging.info(f"스토리지 파일 {deleted_count}개 삭제 완료")
        
        # 2. 메타데이터(file_uploads) 삭제
        # 전체를 뒤져서 해당 room_id인 것만 지워야 하는 비효율이 있지만,
        # 현재 구조상 file_uploads/{school_code} 밑에 플랫하게 있음.
        # 따라서 키를 순회하며 확인해야 함.
        files_ref = db.reference(f"file_uploads/{school_code}")
        files_data = files_ref.get()
        if files_data:
            for file_key, file_val in files_data.items():
                if isinstance(file_val, dict) and file_val.get("room_id") == room_id:
                    db.reference(f"file_uploads/{school_code}/{file_key}").delete()
        
        # 3. 방 데이터(rooms) 삭제
        db.reference(f"rooms/{school_code}/{room_id}").delete()
        
        # 4. 로컬 세션 클리어
        st.session_state.room_id = None
        st.session_state.room_name = None
        st.session_state.processing_step = "start"
        if school_code in st.session_state.school_dataframes:
            del st.session_state.school_dataframes[school_code]
            
        logging.info("방 데이터 삭제 완료")
        return True
        
    except Exception as e:
        st.error(f"방 삭제/초기화 중 오류 발생: {e}")
        return False

# (구) 세션 초기화 - 삭제 예정이거나 전체 초기화용으로 남김
def reset_session_legacy():
    # ... 코드 유지 ...
    pass

# 관리자 전용: 모든 Firebase 데이터 삭제
def admin_reset_all_firebase_data():
    """
    관리자 전용: Firebase의 모든 데이터를 영구적으로 삭제합니다.
    - Storage: 모든 업로드된 파일
    - Realtime DB: rooms, file_uploads, sessions 전체
    - 로컬 세션 상태
    
    Returns:
        tuple: (success: bool, result: int or str)
               success=True이면 result는 삭제된 파일 수
               success=False이면 result는 에러 메시지
    """
    global firebase_available
    
    if not firebase_available:
        return False, "Firebase가 연결되지 않았습니다."
    
    try:
        logging.warning("⚠️ 관리자 전체 데이터 삭제 시작")
        
        # 1. Firebase Storage 모든 파일 삭제
        try:
            bucket = storage.bucket()
            blobs = list(bucket.list_blobs())
            deleted_count = 0
            
            for blob in blobs:
                try:
                    blob.delete()
                    deleted_count += 1
                    logging.info(f"Storage 파일 삭제: {blob.name}")
                except Exception as e:
                    logging.warning(f"Blob 삭제 실패: {blob.name} - {e}")
            
            logging.info(f"✅ Storage 파일 {deleted_count}개 삭제 완료")
        except Exception as e:
            logging.error(f"Storage 삭제 중 오류: {e}")
            deleted_count = 0
        
        # 2. Realtime Database 전체 노드 삭제
        try:
            db.reference("rooms").delete()
            logging.info("✅ rooms 노드 삭제 완료")
        except Exception as e:
            logging.warning(f"rooms 삭제 중 오류: {e}")
        
        try:
            db.reference("file_uploads").delete()
            logging.info("✅ file_uploads 노드 삭제 완료")
        except Exception as e:
            logging.warning(f"file_uploads 삭제 중 오류: {e}")
        
        try:
            db.reference("sessions").delete()
            logging.info("✅ sessions 노드 삭제 완료")
        except Exception as e:
            logging.warning(f"sessions 삭제 중 오류: {e}")
        
        # 3. 로컬 세션 상태 전체 초기화
        keys_to_delete = list(st.session_state.keys())
        for key in keys_to_delete:
            try:
                del st.session_state[key]
            except Exception:
                pass
        
        logging.warning(f"⚠️ 관리자 전체 데이터 삭제 완료 (Storage 파일 {deleted_count}개)")
        return True, deleted_count
        
    except Exception as e:
        error_msg = f"전체 데이터 삭제 중 오류 발생: {e}"
        logging.error(error_msg)
        return False, error_msg


# 페이지 로드 시 사용자 상태 업데이트
update_user_status()

# 세션 상태 확인 및 동기화
if firebase_available:
    remote_state = get_session_state()
    if 'processing_step' in st.session_state:
        # 원격 상태가 강제 초기화된 경우
        if remote_state == "start" and st.session_state.processing_step != "start":
            st.session_state.processing_step = "start"
            st.warning("다른 사용자가 세션을 초기화했습니다.")
            st.rerun()
        # 원격 상태가 다음 단계로 진행된 경우
        elif remote_state == "converting" and st.session_state.processing_step == "start":
            st.session_state.processing_step = "converting"
            st.info("다른 사용자가 데이터 처리를 시작했습니다.")
            st.rerun()
        elif remote_state == "results" and st.session_state.processing_step != "results":
            st.session_state.processing_step = "results"
            st.success("데이터 처리가 완료되었습니다.")
            st.rerun()

# 사이드바에 협업 정보 표시
with st.sidebar:
    st.subheader("협업 정보")
    active_users = get_active_users()
    st.write(f"현재 활성 사용자: {active_users}명")
    
    # 선택한 학교의 공유 파일 업로드 사용자 수 표시
    if firebase_available and 'school_code' in st.session_state and st.session_state.school_code:
        try:
            school_code = st.session_state.school_code
            school_info = None
            
            # 학교 정보 가져오기
            if 'school_list' in st.session_state and st.session_state.school_list:
                school_info = next((s for s in st.session_state.school_list if s['SD_SCHUL_CODE'] == school_code), None)
            
            # 파일 업로드 정보 가져오기
            files_path = f"file_uploads/{school_code}"
            files_data = db.reference(files_path).get()
            
            if files_data:
                unique_users = set()
                file_count = 0
                room_status = {}
                
                # 파일 메타데이터에서 사용자 ID 추출
                for file_key, file_info in files_data.items():
                    file_count += 1
                    if 'upload_user' in file_info:
                        unique_users.add(file_info['upload_user'])
                    room_id = file_info.get("room_id") or "room:미지정"
                    room_name = file_info.get("room_name") or room_id
                    if room_id not in room_status:
                        room_status[room_id] = {
                            "room_name": room_name,
                            "count": 0,
                            "users": set()
                        }
                    room_status[room_id]["count"] += 1
                    if 'upload_user' in file_info:
                        room_status[room_id]["users"].add(file_info['upload_user'])
                
                # 학교 이름 표시
                school_name = "알 수 없음"
                if school_info:
                    school_name = f"{school_info['SCHUL_NM']} ({school_info['ATPT_OFCDC_SC_NM']})"
                elif files_data and next(iter(files_data.values())).get('school_name'):
                    school_name = next(iter(files_data.values())).get('school_name')
                
                st.write(f"**{school_name}** 파일 공유 현황:")
                st.write(f"- 공유된 파일 수: {file_count}개")
                st.write(f"- 파일 공유 사용자 수: {len(unique_users)}명")

                # 방 상태(업로드 완료 인원) 표시
                if st.session_state.get("room_id"):
                    room_info, ready_cnt, total_cnt = get_room_status(school_code, st.session_state.room_id)
                    room_name = room_info.get("room_name", st.session_state.room_id) if room_info else st.session_state.room_id
                    required = room_info.get("required_count", st.session_state.get("room_required_count", 0)) if room_info else st.session_state.get("room_required_count", 0)
                    st.write(f"- 방: {room_name} ({st.session_state.room_id})")
                    st.write(f"- 업로드 완료: {ready_cnt}/{required if required else total_cnt or '미설정'}명")
                
                # 방별 파일 현황 표시
                if room_status:
                    st.write("방별 파일 공유 현황:")
                    for rid, info in room_status.items():
                        st.write(f"• {info['room_name']} ({rid}) - 파일 {info['count']}개, 업로드 사용자 {len(info['users'])}명")
        except Exception as e:
            st.warning(f"학교 공유 정보 조회 실패: {e}")
    
    if firebase_available:
        # Firebase 설정 상태 확인
        st.info("Firebase 연결 상태: 활성")
    else:
        st.warning("Firebase 연결 상태: 비활성")
        
        # 설정 도움말 추가
        with st.expander("Firebase 설정 도움말"):
            st.markdown("""
            ### Firebase 데이터베이스 규칙 설정 방법
            
            1. [Firebase 콘솔](https://console.firebase.google.com)에 접속
            2. 프로젝트 선택 후 '실시간 데이터베이스' 메뉴로 이동
            3. '규칙' 탭에서 다음과 같이 규칙을 수정:
            
            ```json
            {
              "rules": {
                ".read": true,
                ".write": true
              }
            }
            ```
            
            4. 변경사항 게시 클릭
            
            ### Firebase Storage 규칙 설정 방법
            
            1. Firebase 콘솔에서 'Storage' 메뉴로 이동
            2. '규칙' 탭에서 다음과 같이 규칙을 수정:
            
            ```
            rules_version = '2';
            service firebase.storage {
              match /b/{bucket}/o {
                match /{allPaths=**} {
                  allow read, write;
                }
              }
            }
            ```
            
            3. '게시' 클릭
            
            > 주의: 이 설정은 모든 사용자에게 읽기/쓰기 권한을 부여합니다. 실제 운영 환경에서는 더 제한적인 규칙을 사용하세요.
            """)
    
    # 관리자 전용: 모든 데이터 초기화 (비밀번호 보호)
    with st.expander("⚠️ 관리자: 모든 데이터 초기화", expanded=False):
        st.warning("⚠️ **위험:** 이 기능은 모든 Firebase 데이터를 영구적으로 삭제합니다!")
        st.markdown("""
        **삭제될 데이터:**
        - 🗃️ Firebase Storage: 모든 업로드된 파일
        - 📊 Realtime Database: rooms, file_uploads, sessions
        - 💾 로컬 세션 상태
        
        **⚠️ 복구 불가능합니다!**
        """)
        
        admin_password = st.text_input(
            "관리자 비밀번호", 
            type="password", 
            key="admin_pwd",
            placeholder="비밀번호 입력"
        )
        
        if st.button("🗑️ 전체 데이터 삭제 실행", type="primary"):
            if admin_password == "3518":
                if firebase_available:
                    # 2단계 확인 - 세션 상태로 확인 단계 저장
                    if 'admin_confirm_step' not in st.session_state:
                        st.session_state.admin_confirm_step = False
                    
                    st.session_state.admin_confirm_step = True
                    st.error("⚠️ **최종 확인:** 모든 방, 파일, 메타데이터가 영구 삭제됩니다!")
                    st.error("정말로 계속하시겠습니까?")
                else:
                    st.error("❌ Firebase가 연결되지 않았습니다.")
            elif admin_password:
                st.error("❌ 비밀번호가 올바르지 않습니다.")
            else:
                st.warning("비밀번호를 입력해주세요.")
        
        # 최종 확인 버튼 (첫 번째 버튼을 클릭한 경우에만 표시)
        if st.session_state.get('admin_confirm_step', False):
            if st.button("⚠️ 확인했습니다. 모든 데이터를 삭제합니다.", type="secondary"):
                with st.spinner("모든 데이터를 삭제하는 중..."):
                    success, result = admin_reset_all_firebase_data()
                    
                if success:
                    st.success(f"✅ 모든 Firebase 데이터 삭제 완료! (Storage 파일 {result}개 삭제)")
                    # 확인 단계 초기화
                    if 'admin_confirm_step' in st.session_state:
                        del st.session_state.admin_confirm_step
                    time.sleep(1)  # 메시지를 볼 시간 제공
                    st.rerun()
                else:
                    st.error(f"❌ 삭제 실패: {result}")
                    # 확인 단계 초기화
                    if 'admin_confirm_step' in st.session_state:
                        del st.session_state.admin_confirm_step


# 사이드바 추가
st.sidebar.title('학교 생활 도우미')

# 프로젝트 선택
project_options = ['이수 가능한 날짜 찾기', '프로젝트 2', '프로젝트 3']
selected_project = st.sidebar.selectbox('프로젝트 선택', project_options)

# 카피라이트 추가
st.sidebar.markdown('---')
st.sidebar.markdown('© 2024 손쌤. All rights reserved.')

# URL 쿼리 파라미터 처리 (세션 공유용)
if 'work_session_id' in st.session_state:
    if 'session' in st.query_params:
        st.session_state.work_session_id = st.query_params['session']
    else:
        st.query_params['session'] = st.session_state.work_session_id

# CSS를 사용하여 컨텐츠를 중앙 정렬
st.markdown(
    """
    <style>
    .reportview-container .main .block-container{
        max-width: 1000px;
        padding-top: 2rem;
        padding-right: 2rem;
        padding-left: 2rem;
        padding-bottom: 2rem;
    }
    .stButton>button {
        width: 100%;
        margin-bottom: 10px;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# 앱 타이틀
st.title("학교 생활 도우미 💻")
st.write("전학공 출장, 조퇴, 연가 등 제외한 이수 가능한 날짜를 찾아주는 도우미입니다")

# 메인 컨텐츠
if selected_project == '이수 가능한 날짜 찾기':
    st.title('전학공 이수 가능한 날짜 찾아줘')

    # 세션 상태 초기화
    if 'school_dataframes' not in st.session_state:
        st.session_state.school_dataframes = {}
    if 'current_school' not in st.session_state:
        st.session_state.current_school = None
    if 'school_list' not in st.session_state:
        st.session_state.school_list = None

    # 세션 상태에 방학 기간과 제외 날짜 추가
    if 'school_vacations' not in st.session_state:
        st.session_state.school_vacations = {}
    if 'school_excluded_dates' not in st.session_state:
        st.session_state.school_excluded_dates = {}

    st.write("이 프로그램은 학교의 전문적 학습공동체 이수 가능한 날짜를 찾아주는 도구입니다.")
    st.write("아래 단계를 따라 진행해 주세요:")

    # 날짜 표시 형식 변경 함수
    def format_date(date_obj):
        """날짜를 '2025년 4월 23일 (수)' 형식으로 변환"""
        weekday_names = {0: '월', 1: '화', 2: '수', 3: '목', 4: '금', 5: '토', 6: '일'}
        weekday = weekday_names[date_obj.weekday()]
        return f"{date_obj.year}년 {date_obj.month}월 {date_obj.day}일 ({weekday})"

    # API 호출 함수
    def get_school_info(school_name):
        url = "http://open.neis.go.kr/hub/schoolInfo"
        params = {
            'KEY': "f7a477da33d9467ea5835f01e4983e22",
            'Type': 'json',
            'pIndex': '1',
            'pSize': '100',
            'SCHUL_NM': school_name
        }
        response = requests.get(url, params=params)
        data = json.loads(response.text)
        
        if 'schoolInfo' in data:
            school_list = data['schoolInfo'][1]['row']
            return school_list
        else:
            return None

    # 학교 검색
    st.subheader("1. 학교 검색")
    st.write("먼저, 학교를 검색해야 합니다. 학교명을 입력하고 '학교 검색' 버튼을 클릭하세요.")
    school_name = st.text_input("학교명을 입력하세요")
    if st.button("학교 검색"):
        if school_name:
            st.session_state.school_list = get_school_info(school_name)
            if st.session_state.school_list:
                st.success(f"{len(st.session_state.school_list)}개의 학교를 찾았습니다.")
            else:
                st.error("학교를 찾을 수 없습니다.")
        else:
            st.warning("학교명을 입력해주세요.")

    # 학교 선택 부분에서 school_code를 정의합니다
    if st.session_state.school_list:
        st.subheader("2. 학교 선택")
        st.write("검색 결과에서 원하는 학교를 선택하고 '선택한 학교로 진행' 버튼을 클릭하세요.")
        selected_school = st.selectbox(
            "학교를 선택하세요",
            options=st.session_state.school_list,
            format_func=lambda x: f"{x['SCHUL_NM']} ({x['ATPT_OFCDC_SC_NM']})"
        )
        if st.button("선택한 학교로 진행"):
            st.session_state.current_school = selected_school
            st.session_state.school_code = selected_school['SD_SCHUL_CODE']  # 여기서 school_code를 세션 상태에 저장
            st.success(f"선택된 학교: {selected_school['SCHUL_NM']} ({selected_school['ATPT_OFCDC_SC_NM']})")

    # 전학공 협업 방 선택/생성
    if st.session_state.school_code:
        st.subheader("2-1. 전학공 생성")
        school_code = st.session_state.school_code
        
        # 방 선택/생성 UI는 방에 참여하지 않은 경우에만 표시
        if not st.session_state.room_id:
            with st.expander("방 목록 보기 / 생성하기", expanded=True):
                rooms = get_rooms_for_school(school_code) if firebase_available else {}
                room_options = []
                room_labels = {}
                for rid, info in rooms.items():
                    req = info.get("required_count", 0)
                    participants = info.get("participants", {}) or {}
                    ready = sum(1 for p in participants.values() if p.get("uploaded"))
                    name = info.get("room_name", rid)
                    has_password = info.get("has_password", False)
                    password_icon = "🔒 " if has_password else ""
                    label = f"{password_icon}{name} ({rid}) - 필요 {req}명 / 완료 {ready}명"
                    room_options.append(rid)
                    room_labels[rid] = label
                
                selected_room = st.selectbox(
                    "기존 방 선택",
                    options=room_options if room_options else ["없음"],
                    format_func=lambda x: room_labels.get(x, x),
                    key="room_select_box"
                )
                
                # 기존 방 참여
                if firebase_available and selected_room != "없음":
                    st.markdown("---")
                    st.subheader("📥 기존 방 참여")
                    
                    # 비밀번호가 필요한 방인지 확인
                    room_info = get_room_status(school_code, selected_room)[0]
                    has_password = room_info.get("has_password", False) if room_info else False
                    
                    if has_password:
                        join_password = st.text_input(
                            "방 비밀번호", 
                            type="password",
                            key="join_room_password",
                            placeholder="이 방은 비밀번호로 보호되어 있습니다"
                        )
                        
                        if st.button("🔓 선택한 방 참여", use_container_width=True):
                            if join_password and join_password.strip():
                                if verify_room_password(school_code, selected_room, join_password):
                                    if join_room(school_code, selected_room):
                                        st.session_state.room_id = selected_room
                                        st.session_state.room_required_count = int(room_info.get("required_count", 0)) if room_info else 0
                                        st.success(f"{selected_room} 방에 참여했습니다.")
                                        st.rerun()
                                    else:
                                        st.error("방 참여에 실패했습니다.")
                                else:
                                    st.error("❌ 비밀번호가 일치하지 않습니다.")
                            else:
                                st.warning("비밀번호를 입력해주세요.")
                    else:
                        if st.button("📥 선택한 방 참여", use_container_width=True):
                            if join_room(school_code, selected_room):
                                room_info, ready, total = get_room_status(school_code, selected_room)
                                st.session_state.room_id = selected_room
                                st.session_state.room_required_count = int(room_info.get("required_count", 0)) if room_info else 0
                                st.success(f"{selected_room} 방에 참여했습니다.")
                                st.rerun()
                            else:
                                st.error("방 참여에 실패했습니다.")
                
                # 새 방 생성 섹션 (expander로 감싸기)
                st.markdown("---")
                with st.expander("➕ 새 방 생성하기", expanded=False):
                    st.info("💡 새로운 협업 방을 만들려면 아래 정보를 입력하고 '새 방 생성' 버튼을 눌러주세요.")
                    
                    required_input = st.number_input("필요 인원 수", min_value=1, max_value=30, value=3, step=1, key="new_room_required")
                    room_name_input = st.text_input("방 이름", placeholder="예) 3학년 전학공 방", key="new_room_name")
                    room_password_input = st.text_input("방 비밀번호 (선택사항)", type="password", 
                                                       placeholder="방 삭제 시 필요한 비밀번호를 설정하세요",
                                                       help="비밀번호를 설정하면 해당 비밀번호를 아는 사람만 방을 삭제할 수 있습니다.",
                                                       key="new_room_password")
                    
                    # 버튼 클릭 여부를 명시적으로 체크
                    create_button_clicked = st.button("➕ 새 방 생성", use_container_width=True, type="primary", key="create_new_room_button")
                    
                    if create_button_clicked:
                        if firebase_available:
                            new_room = create_room(school_code, required_input, room_name_input.strip(), room_password_input)
                            if new_room:
                                st.session_state.room_id = new_room
                                st.session_state.room_required_count = int(required_input)
                                join_room(school_code, new_room)
                                if room_password_input and room_password_input.strip():
                                    st.success(f"새 방 생성 및 참여 완료: {new_room} (비밀번호 설정됨)")
                                else:
                                    st.success(f"새 방 생성 및 참여 완료: {new_room}")
                                st.rerun()
                            else:
                                st.error("방 생성에 실패했습니다. 네트워크 상태를 확인하세요.")
                        else:
                            st.warning("Firebase 연결이 필요합니다.")
        
        # 참여/완료 상태 표시
        if firebase_available and st.session_state.room_id:
            room_info, ready_cnt, total_cnt = get_room_status(school_code, st.session_state.room_id)
            room_name = room_info.get("room_name", st.session_state.room_id) if room_info else st.session_state.room_id
            st.session_state.room_name = room_name
            st.info(f"현재 방: {room_name} ({st.session_state.room_id}) | 업로드 완료 {ready_cnt}/{room_info.get('required_count', st.session_state.room_required_count)}명 (참여 {total_cnt}명)")
            
            # 방 관리 섹션 (모든 사용자가 볼 수 있지만, 비밀번호가 있으면 비밀번호를 아는 사람만 삭제 가능)
            has_password = room_info.get("has_password", False) if room_info else False
            creator_id = room_info.get("created_by") if room_info else None
            is_owner = (creator_id == st.session_state.session_id)
            
            # 방 관리 UI를 expander로 변경
            with st.expander("⚙️ 방 관리", expanded=False):
                # 방 나가기 버튼
                if st.button("🚪 방 나가기"):
                    st.session_state.room_id = None
                    st.session_state.room_name = None
                    # URL에서 room_id 제거
                    if 'room_id' in st.query_params:
                        del st.query_params['room_id']
                    st.success("방에서 나갔습니다.")
                    st.rerun()
                
                st.divider()
                if has_password:
                    st.info("🔒 이 방은 비밀번호로 보호되고 있습니다.")
                    if is_owner:
                        st.success("👑 당신은 이 방의 방장입니다.")
                    
                    # 비밀번호 입력 필드
                    delete_password = st.text_input(
                        "방 삭제 비밀번호", 
                        type="password",
                        key="delete_room_password",
                        placeholder="방 생성 시 설정한 비밀번호를 입력하세요"
                    )
                    
                    if st.button("🚨 이 방 삭제 및 초기화", type="primary"):
                        if delete_password and delete_password.strip():
                            if reset_room(school_code, st.session_state.room_id, delete_password):
                                st.success("방과 관련된 모든 파일이 삭제되었습니다.")
                                st.session_state.room_id = None
                                st.rerun()
                            # reset_room 내부에서 비밀번호 오류 메시지 출력
                        else:
                            st.warning("비밀번호를 입력해주세요.")
                else:
                    # 비밀번호가 없는 경우 - 방장만 삭제 가능
                    if is_owner:
                        st.success("👑 당신은 이 방의 방장입니다.")
                        st.warning("⚠️ 이 방은 비밀번호로 보호되지 않습니다. 방장만 삭제할 수 있습니다.")
                        if st.button("🚨 이 방 삭제 및 초기화", type="primary"):
                            if reset_room(school_code, st.session_state.room_id):
                                st.success("방과 관련된 모든 파일이 삭제되었습니다.")
                                st.session_state.room_id = None
                                # URL에서 room_id 제거
                                if 'room_id' in st.query_params:
                                    del st.query_params['room_id']
                                st.rerun()
                    else:
                        st.info(f"방장: {creator_id[:8]}..." if creator_id else "방장 미상")
                        st.warning("방 삭제는 방장만 가능합니다.")

    # 업로드된 파일 목록 표시
    if firebase_available and st.session_state.processing_step == 'start':
        all_files = get_all_uploaded_files()
        # 현재 방의 파일만 필터링
        current_room_id = st.session_state.get("room_id")
        if current_room_id:
            # 방이 설정되어 있으면 해당 방의 파일만 표시
            display_files = [f for f in all_files if f.get("room_id") == current_room_id]
        else:
            # 방이 없으면 모든 파일 표시 (하위 호환성)
            display_files = all_files
            
        if display_files:
            if current_room_id:
                st.write(f"### 현재 방({st.session_state.get('room_name', current_room_id)})의 업로드된 파일 목록")
            else:
                st.write("### 현재 업로드된 파일 목록")
            file_info = []
            for file in display_files:
                upload_ts = file.get("upload_time", 0)
                try:
                    upload_ts = float(upload_ts)
                    file_time = datetime.fromtimestamp(upload_ts).strftime('%Y-%m-%d %H:%M:%S')
                except Exception:
                    file_time = "알 수 없음"
                file_info.append({
                    "파일명": file.get("filename", "알 수 없음"),
                    "업로드 시간": file_time,
                    "업로드 ID": (file.get("user_id", "unknown")[:8] + "...")
                })
            st.dataframe(pd.DataFrame(file_info), use_container_width=True)

    # 데이터 업로드 기능
    st.subheader("3. 데이터 업로드")

    if 'school_dataframes' not in st.session_state:
        st.session_state.school_dataframes = {}

    # 선택된 학교 정보 표시
    if not st.session_state.school_code:
        st.warning("먼저 상단에서 학교를 검색하고 선택한 후 '선택한 학교로 진행' 버튼을 클릭해주세요.")
        school_code = None
    else:
        school_code = st.session_state.school_code
        school_info = next((s for s in st.session_state.school_list if s['SD_SCHUL_CODE'] == school_code), None)
        if school_info:
            st.success(f"선택된 학교: {school_info['SCHUL_NM']} ({school_info['ATPT_OFCDC_SC_NM']})")
        else:
            st.info(f"선택된 학교 코드: {school_code}")
        
        # 방에 참여 중이면 해당 방의 파일 자동 로드
        if firebase_available and st.session_state.room_id:
            # 파일이 로드되지 않았으면 로드 (세션 상태가 비어있을 때)
            current_files = st.session_state.school_dataframes.get(school_code, [])
            
            if len(current_files) == 0:  # 파일이 없으면 로드
                with st.spinner("방의 업로드된 파일을 불러오는 중..."):
                    all_files = get_all_uploaded_files()
                    # 현재 방의 파일만 필터링
                    room_files = [f for f in all_files if f.get("room_id") == st.session_state.room_id]
                    
                    if room_files:
                        loaded_count = 0
                        for file in room_files:
                            # 파일 다운로드 및 로드
                            df = download_firebase_file(file["user_id"], file["filename"])
                            if df is not None:
                                if school_code not in st.session_state.school_dataframes:
                                    st.session_state.school_dataframes[school_code] = []
                                
                                # 중복 체크
                                already_exists = any(
                                    item['filename'] == file["filename"] 
                                    for item in st.session_state.school_dataframes[school_code]
                                )
                                
                                if not already_exists:
                                    st.session_state.school_dataframes[school_code].append({
                                        'dataframe': df,
                                        'filename': file["filename"]
                                    })
                                    loaded_count += 1
                        
                        if loaded_count > 0:
                            st.success(f"✅ {loaded_count}개의 파일을 불러왔습니다!")

    # 파일 업로드
    st.subheader("📤 파일 업로드")
    
    # 중요 안내 메시지 (항상 표시)
    st.info("ℹ️ **사용 방법:**\n1. 아래에서 파일을 선택하세요\n2. 파일이 맞는지 확인하세요 (수정이 필요하면 다시 선택 가능)\n3. **'📤 파일 저장 및 공유하기' 버튼을 꼭 눌러주세요!** (이 버튼을 눌러야 다른 사람들도 볼 수 있습니다)")
    
    uploaded_files = st.file_uploader("엑셀 파일 업로드 (여러 파일 가능)", type=["xlsx", "xls"], accept_multiple_files=True)
    
    # 파일을 선택했지만 아직 저장하지 않은 경우 경고 표시
    if uploaded_files:
        st.warning("⚠️ **중요:** 파일을 선택했습니다! 아래 '📤 파일 저장 및 공유하기' 버튼을 눌러야 업로드가 완료됩니다!")
        st.write(f"선택된 파일: {', '.join([f.name for f in uploaded_files])}")

    # 협업 방 업로드 완료 표시 (이 위치가 자연스러운 UI 흐름)
    if firebase_available and st.session_state.room_id:
        with st.expander("✅ 내 업로드 완료 표시", expanded=False):
            st.write("모든 파일 업로드 후 완료 버튼을 눌러주세요.")
            if st.button("✅ 내 업로드 완료", key="mark_uploaded_done_button"):
                mark_uploaded_done(st.session_state.school_code, st.session_state.room_id)
                st.success("업로드 완료 상태가 기록되었습니다.")
                st.rerun()

    # 현재 업로드된 파일 목록 표시
    if school_code and school_code in st.session_state.school_dataframes and st.session_state.school_dataframes[school_code]:
        st.write("### 💾 저장된 파일 목록")
        for idx, file_info in enumerate(st.session_state.school_dataframes[school_code]):
            st.write(f"{idx+1}. ✓ {file_info.get('filename', '알 수 없는 파일')}")

    # 업로드 버튼 (Firebase 저장용)
    upload_button = st.button("📤 파일 저장 및 공유하기", type="primary", use_container_width=True)
    if upload_button:
        if not school_code:
            st.error("먼저 학교를 선택해주세요.")
        elif not uploaded_files:
            st.warning("업로드할 파일을 선택해주세요.")
        else:
            with st.spinner("파일 업로드 중..."):
                for uploaded_file in uploaded_files:
                    # 기존 Streamlit 세션 상태 저장
                    if school_code not in st.session_state.school_dataframes:
                        st.session_state.school_dataframes[school_code] = []
                    
                    try:
                        df = pd.read_excel(uploaded_file)
                        st.session_state.school_dataframes[school_code].append({'dataframe': df, 'filename': uploaded_file.name})
                        
                        # Firebase에도 파일 저장
                        if firebase_available and db is not None:
                            try:
                                save_uploaded_file(uploaded_file, school_code, school_info['SCHUL_NM'])
                                st.success(f"{uploaded_file.name} 업로드 및 공유 성공!")
                            except Exception as e:
                                st.warning(f"{uploaded_file.name} 파일 공유 실패 (로컬에만 저장됨): {e}")
                        else:
                            st.success(f"{uploaded_file.name} 로컬에 업로드 성공!")
                    except Exception as e:
                        st.error(f"{uploaded_file.name} 업로드 실패: {e}")
            
            st.rerun()

    # 데이터 처리 시작 시 Firebase의 파일 데이터 동기화
    if firebase_available and st.session_state.processing_step == 'converting' and 'all_files_loaded' not in st.session_state:
        with st.spinner("다른 사용자가 업로드한 파일을 로드 중..."):
            all_files = get_all_uploaded_files()
            # 현재 방의 파일만 필터링
            current_room_id = st.session_state.get("room_id")
            if current_room_id:
                # 방이 설정되어 있으면 해당 방의 파일만 로드
                room_files = [f for f in all_files if f.get("room_id") == current_room_id]
            else:
                # 방이 없으면 모든 파일 로드 (하위 호환성)
                room_files = all_files
            
            for file in room_files:
                # 이미 로컬에 있는 파일은 건너뜀
                already_loaded = False
                if school_code in st.session_state.school_dataframes:
                    for loaded_file in st.session_state.school_dataframes[school_code]:
                        if loaded_file.get('filename') == file["filename"]:
                            already_loaded = True
                            break
                
                if not already_loaded:
                    df = download_firebase_file(file["user_id"], file["filename"])
                    if df is not None:
                        if school_code not in st.session_state.school_dataframes:
                            st.session_state.school_dataframes[school_code] = []
                        st.session_state.school_dataframes[school_code].append({
                            'dataframe': df, 
                            'filename': file["filename"]
                        })
        
        st.session_state.all_files_loaded = True
        if current_room_id:
            st.info(f"방 '{st.session_state.get('room_name', current_room_id)}'의 모든 공유 파일이 로드되었습니다.")
        else:
            st.info("모든 공유 파일이 로드되었습니다.")

    # 업로드된 데이터 초기화 버튼
    if school_code in st.session_state.school_dataframes and st.session_state.school_dataframes[school_code]:
        if st.button("업로드된 데이터 초기화"):
            st.session_state.school_dataframes[school_code] = []
            st.success("데이터가 초기화되었습니다.")
            st.rerun()

    # 방학 기간 설정
    st.subheader("4. 방학 기간 설정")
    st.write("여름 방학과 겨울 방학 기간을 설정하세요. 이 기간은 이수 가능한 날짜에서 제외됩니다.")
    
    col1, col2 = st.columns(2)
    with col1:
        summer_start = st.date_input("여름 방학 시작일", value=datetime(2025, 7, 26))
        summer_end = st.date_input("여름 방학 종료일", value=datetime(2025, 8, 19))
    with col2:
        winter_start = st.date_input("겨울 방학 시작일", value=datetime(2026, 1, 1))
        winter_end = st.date_input("겨울 방학 종료일", value=datetime(2026, 2, 28))
    
    if st.button("방학 기간 저장"):
        if not st.session_state.school_code:
            st.error("먼저 학교를 선택해주세요.")
        else:
            school_code = st.session_state.school_code
            st.session_state.school_vacations[school_code] = {
                "summer": (summer_start, summer_end),
                "winter": (winter_start, winter_end)
            }
            st.success("방학 기간이 저장되었습니다.")

    # 제외 날짜 추가
    st.subheader("5. 제외 날짜 추가")
    st.write("특정 날짜를 추가로 제외하고 싶다면 여기서 설정하세요.")
    excluded_date = st.date_input("제외할 날짜 선택")
    if st.button("제외 날짜 추가"):
        if not st.session_state.school_code:
            st.error("먼저 학교를 선택해주세요.")
        else:
            school_code = st.session_state.school_code
            if school_code not in st.session_state.school_excluded_dates:
                st.session_state.school_excluded_dates[school_code] = set()
            st.session_state.school_excluded_dates[school_code].add(excluded_date)
            st.success(f"{excluded_date}가 제외 날짜로 추가되었습니다.")

    # 현재 제외된 날짜 표시
    if not st.session_state.school_code:
        st.info("제외된 날짜를 보려면 먼저 학교를 선택해주세요.")
    else:
        school_code = st.session_state.school_code
        if school_code in st.session_state.school_excluded_dates and st.session_state.school_excluded_dates[school_code]:
            st.write("현재 제외된 날짜:")
            st.write(sorted(st.session_state.school_excluded_dates[school_code]))
        else:
            st.info("아직 제외된 날짜가 없습니다.")

    # 한국 공휴일 정보를 동적으로 가져오기
    # 현재 날짜를 기준으로 연도 판단 (3-2월 학년도 기준)
    cal = SouthKorea()
    current_date = datetime.now()
    
    # 현재가 3월 이후면 현재 연도와 다음 연도, 3월 이전이면 전년도와 현재 연도
    if current_date.month >= 3:
        year_start = current_date.year
        year_end = current_date.year + 1
    else:
        year_start = current_date.year - 1
        year_end = current_date.year
    
    holidays_start = cal.holidays(year_start)
    holidays_end = cal.holidays(year_end)
    all_holidays = holidays_start + holidays_end
    
    st.info(f"📅 공휴일 자동 제외: {year_start}년, {year_end}년 대한민국 공휴일이 자동으로 제외됩니다.")
    
    # 공휴일 목록 표시 (접이식)
    with st.expander("🗓️ 제외되는 공휴일 목록 보기", expanded=False):
        st.write(f"### {year_start}년 공휴일")
        for holiday_date, holiday_name in sorted(holidays_start):
            st.write(f"- {holiday_date.strftime('%Y년 %m월 %d일')}: {holiday_name}")
        
        st.write(f"### {year_end}년 공휴일")
        for holiday_date, holiday_name in sorted(holidays_end):
            st.write(f"- {holiday_date.strftime('%Y년 %m월 %d일')}: {holiday_name}")
        
        st.info(f"총 {len(all_holidays)}개의 공휴일이 자동으로 제외됩니다.")

    # 날짜 객체 정규화 함수
    def normalize_date(date_obj):
        """
        다양한 날짜 객체 타입을 datetime.date 타입으로 통일
        """
        if pd.isna(date_obj):
            return None
        
        if isinstance(date_obj, datetime):
            return date_obj.date()
        elif isinstance(date_obj, pd.Timestamp):
            return date_obj.date()
        elif isinstance(date_obj, str):
            try:
                return pd.to_datetime(date_obj).date()
            except:
                return None
        else:
            return date_obj  # 이미 date 객체이거나 처리할 수 없는 경우

    # 날짜 처리 함수
    def extract_date(date_string, is_period_column=False):
        """
        다양한 형식의 날짜 문자열에서 날짜를 추출하는 함수
        is_period_column: 출장기간/기간 컬럼 여부
        """
        # NaN 또는 빈 값 처리
        if pd.isna(date_string) or date_string == "" or date_string is None:
            return None
            
        # 문자열이 아닌 경우 처리
        if not isinstance(date_string, str):
            try:
                # datetime, Timestamp 등의 객체를 datetime.date로 변환
                return normalize_date(date_string)
            except:
                return None
        
        # 문자열 앞뒤 공백 제거
        date_string = date_string.strip()
        
        try:
            # 0. 로깅용 정보 출력
            logger.info(f"날짜 추출 시도: '{date_string}'")
            
            # 1-0. 특수 컬럼(출장기간/기간) 처리
            if is_period_column:
                # 2025.04.23 14:00 ~ 2025.04.23 16:40 패턴 처리
                if ' ~ ' in date_string:
                    first_part = date_string.split(' ~ ')[0].strip()
                    logger.debug(f"기간 컬럼 ~ 앞 부분: '{first_part}'")
                    
                    # 공백이 있는 경우 처리 (날짜+시간)
                    if ' ' in first_part:
                        date_part = first_part.split(' ')[0].strip()
                        logger.debug(f"기간 컬럼 날짜 부분: '{date_part}'")
                    else:
                        date_part = first_part
                    
                    # 2025.04.23 형식
                    if '.' in date_part:
                        try:
                            year, month, day = map(int, date_part.split('.'))
                            logger.info(f"기간 컬럼 날짜 추출 성공: {year}-{month}-{day}")
                            return datetime(year, month, day).date()
                        except Exception as e:
                            logger.debug(f"기간 컬럼 날짜 추출 실패(점 구분자): {e}")
                    
                    # 2025-04-23 형식
                    elif '-' in date_part:
                        try:
                            year, month, day = map(int, date_part.split('-'))
                            logger.info(f"기간 컬럼 날짜 추출 성공: {year}-{month}-{day}")
                            return datetime(year, month, day).date()
                        except Exception as e:
                            logger.debug(f"기간 컬럼 날짜 추출 실패(하이픈 구분자): {e}")
            
            # 1. "YYYY.MM.DD HH:MM ~ YYYY.MM.DD HH:MM" 형식 처리
            if ' ~ ' in date_string:
                # '~' 기호 앞의 부분만 추출
                first_part = date_string.split(' ~ ')[0].strip()
                logger.debug(f"~ 기호 앞 부분: '{first_part}'")
                
                # 날짜와 시간이 있는 경우, 날짜 부분만 추출
                if ' ' in first_part:
                    date_part = first_part.split(' ')[0].strip()
                    logger.debug(f"날짜 부분만 추출: '{date_part}'")
                else:
                    date_part = first_part
                
                # 점(.) 또는 하이픈(-) 구분자 있는지 확인
                if '.' in date_part:
                    # 2025.04.23 형식
                    try:
                        year, month, day = map(int, date_part.split('.'))
                        logger.debug(f"날짜 추출 성공 (형식1): {year}-{month}-{day}")
                        return datetime(year, month, day).date()
                    except Exception as e:
                        logger.debug(f"날짜 추출 실패 (형식1): {e}")
                        pass  # 변환 실패 시 다음 단계로
                elif '-' in date_part:
                    # 2025-04-23 형식
                    try:
                        year, month, day = map(int, date_part.split('-'))
                        logger.debug(f"날짜 추출 성공 (형식2): {year}-{month}-{day}")
                        return datetime(year, month, day).date()
                    except Exception as e:
                        logger.debug(f"날짜 추출 실패 (형식2): {e}")
                        pass  # 변환 실패 시 다음 단계로
            
            # 2. 단순 날짜 형식 (YYYY.MM.DD 또는 YYYY-MM-DD) 처리
            if '.' in date_string and date_string.count('.') == 2:
                # 2025.04.23 형식
                try:
                    parts = date_string.split('.')
                    if len(parts) == 3 and len(parts[0]) == 4:  # 연도가 4자리인지 확인
                        year, month, day = map(int, parts)
                        logger.debug(f"날짜 추출 성공 (형식3): {year}-{month}-{day}")
                        return datetime(year, month, day).date()
                except Exception as e:
                    logger.debug(f"날짜 추출 실패 (형식3): {e}")
                    pass  # 변환 실패 시 다음 단계로
            
            if '-' in date_string and date_string.count('-') == 2:
                # 2025-04-23 형식
                try:
                    parts = date_string.split('-')
                    if len(parts) == 3 and len(parts[0]) == 4:  # 연도가 4자리인지 확인
                        year, month, day = map(int, parts)
                        logger.debug(f"날짜 추출 성공 (형식4): {year}-{month}-{day}")
                        return datetime(year, month, day).date()
                except Exception as e:
                    logger.debug(f"날짜 추출 실패 (형식4): {e}")
                    pass  # 변환 실패 시 다음 단계로
            
            # 3. 정규 표현식으로 날짜 부분 추출
            date_pattern = r'\b(\d{4})[./-](\d{1,2})[./-](\d{1,2})\b'
            match = re.search(date_pattern, date_string)
            if match:
                try:
                    year, month, day = map(int, match.groups())
                    logger.debug(f"날짜 추출 성공 (정규식): {year}-{month}-{day}")
                    return datetime(year, month, day).date()
                except Exception as e:
                    logger.debug(f"날짜 추출 실패 (정규식): {e}")
                    pass  # 변환 실패 시 다음 단계로
            
            # 4. pandas의 자동 변환 시도
            try:
                date_obj = pd.to_datetime(date_string)
                logger.debug(f"날짜 추출 성공 (pandas): {date_obj.date()}")
                return date_obj.date()
            except Exception as e:
                logger.debug(f"날짜 추출 실패 (pandas): {e}")
                pass  # 변환 실패 시 다음 단계로
            
            # 5. 출장/휴가 특수 패턴 처리
            vacation_pattern = r'(\d{4})-(\d{1,2})-(\d{1,2}) \d{1,2}:\d{1,2} ~ \d{4}-\d{1,2}-\d{1,2}'
            if re.search(vacation_pattern, date_string):
                try:
                    parts = date_string.split(' ')[0].split('-')
                    year, month, day = map(int, parts)
                    logger.debug(f"날짜 추출 성공 (휴가 특수패턴): {year}-{month}-{day}")
                    return datetime(year, month, day).date()
                except Exception as e:
                    logger.debug(f"날짜 추출 실패 (휴가 특수패턴): {e}")
                    pass
            
            # 모든 변환 시도 실패
            logger.warning(f"모든 방법으로 날짜 추출 실패: '{date_string}'")
            return None
                
        except Exception as e:
            # 변환 실패
            logger.error(f"날짜 추출 중 예외 발생: {e}, 원본: '{date_string}'")
            return None

    # 날짜 처리 함수 수정
    def process_dates(existing_dates, school_code):
        # 현재 날짜를 기준으로 학년도 시작/종료일 계산
        current_date = datetime.now()
        if current_date.month >= 3:
            # 3월 이후: 현재 연도 3월 ~ 다음 연도 2월
            start_date = datetime(current_date.year, 3, 1)
            end_date = datetime(current_date.year + 1, 2, 28)
        else:
            # 3월 이전: 전년도 3월 ~ 현재 연도 2월
            start_date = datetime(current_date.year - 1, 3, 1)
            end_date = datetime(current_date.year, 2, 28)
        
        date_range = pd.date_range(start=start_date, end=end_date)
        available_days = []
        
        vacations = st.session_state.school_vacations.get(school_code, {})
        excluded_dates = st.session_state.school_excluded_dates.get(school_code, set())
        
        summer_vacation = vacations.get("summer", (None, None))
        winter_vacation = vacations.get("winter", (None, None))
        
        # existing_dates의 각 날짜가 datetime.date 타입인지 확인하고 필요시 변환
        existing_dates_set = set()
        for date_obj in existing_dates:
            if isinstance(date_obj, datetime):
                existing_dates_set.add(date_obj.date())
            elif isinstance(date_obj, pd.Timestamp):
                existing_dates_set.add(date_obj.date())
            else:
                existing_dates_set.add(date_obj)  # 이미 date 객체인 경우
        
        for date in date_range:
            curr_date = date.date()
            if (curr_date.weekday() < 5 and 
                curr_date not in [d for d, _ in all_holidays] and 
                curr_date not in existing_dates_set and
                curr_date not in excluded_dates and
                not (summer_vacation[0] and summer_vacation[1] and summer_vacation[0] <= curr_date <= summer_vacation[1]) and
                not (winter_vacation[0] and winter_vacation[1] and winter_vacation[0] <= curr_date <= winter_vacation[1])):
                available_days.append(date)
        
        df = pd.DataFrame({'날짜': available_days})
        df['요일'] = df['날짜'].dt.strftime('%A')
        return df

    # 데이터 처리 부분 수정
    st.subheader("6. 데이터 처리")
    st.write("모든 설정이 완료되면 '데이터 처리하기' 버튼을 클릭하여 결과를 확인하세요.")
    
    # 작업 흐름 제어를 위한 세션 상태
    if 'processing_step' not in st.session_state:
        st.session_state.processing_step = 'start'  # 'start', 'converting', 'results'
    
    # 처리 버튼 활성화 조건 (모든 참여자가 업로드 완료했을 때)
    processing_disabled = False
    disable_reason = ""
    if firebase_available and st.session_state.room_id:
        room_info, ready_cnt, total_cnt = get_room_status(st.session_state.school_code, st.session_state.room_id)
        required = 0
        if room_info:
            required = int(room_info.get("required_count", 0))
            st.session_state.room_required_count = required
        if required > 0 and ready_cnt < required:
            processing_disabled = True
            disable_reason = f"업로드 완료 {ready_cnt}/{required}명 - 모두 완료되면 처리 가능합니다."
        elif total_cnt == 0:
            processing_disabled = True
            disable_reason = "참여자가 없습니다. 방에 참여 후 진행하세요."
    # Firebase 비활성 시에는 로컬 전용이므로 제한 없음

    # 데이터 처리 버튼
    start_processing = st.button("데이터 처리하기", disabled=processing_disabled)
    if disable_reason:
        st.info(disable_reason)
    
    # 데이터 처리 시작
    if start_processing:
        st.session_state.processing_step = 'converting'
        # Firebase에 상태 업데이트 (다른 사용자에게 알림)
        if firebase_available:
            update_session_state("converting")
        st.rerun()

    # 데이터 처리 흐름 시작
    if st.session_state.processing_step != 'start':
        if st.session_state.school_dataframes:
            for school_code, dataframes_info in st.session_state.school_dataframes.items():
                if not dataframes_info:  # 빈 리스트인 경우 스킵
                    continue
                    
                school_info = next((s for s in st.session_state.school_list if s['SD_SCHUL_CODE'] == school_code), None)
                if school_info:
                    st.write(f"## 학교: {school_info['SCHUL_NM']} ({school_info['ATPT_OFCDC_SC_NM']})")
                    
                    # 날짜 변환 단계
                    if st.session_state.processing_step == 'converting':
                        # 리스트에서 데이터프레임만 추출
                        if isinstance(dataframes_info[0], dict) and 'dataframe' in dataframes_info[0]:
                            dataframes = [info['dataframe'] for info in dataframes_info]
                        else:
                            dataframes = dataframes_info
                            
                        combined_df = pd.concat(dataframes)
                        
                        # 데이터 확인을 위한 조치
                        st.write("### 업로드된 모든 원본 데이터 (처리 전)")
                        st.dataframe(combined_df)
                        
                        # 날짜 처리 과정 시작
                        st.write("### 날짜 데이터 처리")
                        
                        # 원본 데이터프레임 초기화 (인덱스 재설정)
                        combined_df = combined_df.reset_index(drop=True)
                        
                        # 현재 컬럼 목록 출력 (디버깅용)
                        st.write("#### 현재 데이터에 포함된 컬럼:")
                        column_list = list(combined_df.columns)
                        for i, col in enumerate(column_list):
                            st.write(f"{i+1}. `{col}`")
                        
                        # 자동으로 날짜가 포함된 컬럼 찾기
                        st.write("#### 날짜 정보 포함 컬럼 자동 탐지")
                        logger.info("날짜 컬럼 자동 탐지 시작")
                        date_columns = []
                        
                        # 우선 처리할 컬럼명 정의
                        priority_columns = ['출장기간', '기간', '휴가기간', '날짜']
                        
                        # 1. 우선 처리할 컬럼명 먼저 확인
                        for priority_col in priority_columns:
                            for col in combined_df.columns:
                                if str(col).lower() == priority_col.lower() or str(col).lower().find(priority_col.lower()) >= 0:
                                    date_columns.append(col)
                                    logger.info(f"우선순위 컬럼 발견: {col} (키워드: {priority_col})")
                                    st.success(f"우선순위 날짜 컬럼 발견: **{col}**")
                        
                        # 2. 키워드로 컬럼명 검색
                        if not date_columns:  # 우선순위 컬럼이 없을 경우에만 다른 키워드 검색
                            for col in combined_df.columns:
                                # 컬럼명에 날짜 관련 키워드가 있는지 확인
                                if any(keyword in str(col).lower() for keyword in ['날짜', 'date', '일시', '기간']):
                                    date_columns.append(col)
                                    logger.info(f"컬럼명 키워드로 찾음: {col}")
                                    continue
                        
                        # 3. 데이터 내용으로 찾기 (위에서 찾은 컬럼이 없을 경우)
                        if not date_columns:
                            for col in combined_df.columns:
                                try:
                                    # 데이터 샘플을 확인하여 날짜 포맷이 포함된 컬럼 찾기
                                    sample_values = combined_df[col].dropna().astype(str).head(10).tolist()
                                    
                                    for val in sample_values:
                                        # 문자열인지 확인하고 날짜 패턴이 포함되어 있는지 확인
                                        if not isinstance(val, str):
                                            continue
                                        
                                        # 2025.04.23 14:00 ~ 2025.04.23 16:40 같은 패턴 확인
                                        if '~' in val and any(year in val for year in ['2025', '2026']):
                                            date_pattern_match = re.search(r'(\d{4})[./-](\d{1,2})[./-](\d{1,2})', val)
                                            if date_pattern_match:
                                                date_columns.append(col)
                                                logger.info(f"날짜 패턴 발견: {col}, 예시: {val}")
                                                st.info(f"날짜 패턴이 발견된 컬럼: **{col}**, 예시: `{val}`")
                                                break
                                except Exception as e:
                                    logger.error(f"컬럼 {col} 처리 중 오류: {e}")
                        
                        # 4. 출장부/휴가부 데이터 특수 처리 - 특정 패턴의 컬럼명 확인
                        if not date_columns:
                            special_date_columns = []
                            for col in combined_df.columns:
                                try:
                                    if isinstance(col, str) and len(col) > 0:
                                        # 출장부/휴가부 특수 형식 확인
                                        if col.isnumeric() and int(col) < 20:  # 컬럼명이 숫자이고 작은 번호일 때 건너뛰기
                                            continue
                                        sample_values = combined_df[col].dropna().astype(str).head(5).tolist()
                                        for val in sample_values:
                                            if isinstance(val, str) and '~' in val and len(val) > 10:
                                                if re.search(r'(\d{4})[-./](\d{1,2})[-./](\d{1,2})', val):
                                                    special_date_columns.append(col)
                                                    logger.info(f"특수 패턴 발견: {col}, 예시: {val}")
                                                    st.info(f"특수 날짜 패턴이 발견된 컬럼: **{col}**, 예시: `{val}`")
                                                    break
                                except Exception as e:
                                    logger.error(f"특수 컬럼 {col} 처리 중 오류: {e}")
                            
                            # 특수 컬럼 추가
                            date_columns.extend(special_date_columns)
                        
                        # 두 리스트 병합 및 중복 제거
                        date_columns = list(dict.fromkeys(date_columns))  # 중복 제거
                        logger.info(f"탐지된 날짜 컬럼 목록: {date_columns}")
                        
                        # 날짜 컬럼이 없으면 사용자에게 알리고 직접 선택하도록 함
                        if not date_columns:
                            st.error("자동으로 날짜 컬럼을 찾을 수 없습니다. 날짜 정보가 포함된 컬럼을 선택해주세요.")
                            st.warning("다음과 같은 형식의 날짜 정보가 있는 컬럼을 선택하세요: '2025.04.23' 또는 '2025.04.23 14:00 ~ 2025.04.23 16:40'")
                            selected_date_columns = st.multiselect(
                                "날짜 정보가 포함된 컬럼 선택 (여러 개 선택 가능)", 
                                options=combined_df.columns
                            )
                            if selected_date_columns:
                                date_columns = selected_date_columns
                            else:
                                st.stop()
                        elif len(date_columns) > 1:
                            # 우선순위 키워드가 포함된 컬럼을 먼저 선택 (기본값으로 설정)
                            default_indices = []
                            for i, col in enumerate(date_columns):
                                col_lower = str(col).lower()
                                if "출장기간" in col_lower or "기간" in col_lower:
                                    default_indices.append(i)
                            
                            # 기본 선택 항목이 없으면 첫 번째 항목 선택
                            if not default_indices and date_columns:
                                default_indices = [0]
                            
                            default_selections = [date_columns[i] for i in default_indices]
                            
                            st.warning(f"여러 개의 날짜 관련 컬럼이 발견되었습니다: {date_columns}")
                            selected_date_columns = st.multiselect(
                                "사용할 날짜 컬럼 선택 (여러 개 선택 가능)", 
                                options=date_columns,
                                default=default_selections
                            )
                            
                            if not selected_date_columns:
                                st.error("최소 하나 이상의 날짜 컬럼을 선택해주세요.")
                                st.stop()
                            
                            date_columns = selected_date_columns
                        
                        # 선택된 날짜 컬럼 표시 (최종)
                        st.success(f"날짜 처리에 최종 선택된 컬럼: **{', '.join(date_columns)}**")
                        
                        # 날짜 컬럼이 없으면 임시로 생성
                        if '날짜' not in combined_df.columns:
                            # 여러 컬럼이 선택된 경우 첫 번째 컬럼으로 초기화하고 나머지는 병합
                            selected_date_column = date_columns[0]
                            combined_df['날짜'] = combined_df[selected_date_column]
                            logger.info(f"'날짜' 컬럼 초기화: {selected_date_column} 컬럼을 복사하여 생성했습니다.")
                            st.info(f"선택된 **{selected_date_column}** 컬럼을 '날짜' 컬럼으로 사용합니다.")
                        
                        # 원본 날짜 열을 별도로 저장
                        combined_df['원본_날짜'] = combined_df['날짜'].copy().astype(str)
                        logger.info("원본 날짜 컬럼을 별도로 저장했습니다.")
                        
                        # 결과를 저장할 데이터프레임 생성
                        result_df = pd.DataFrame({
                            '원본_날짜': combined_df['원본_날짜'],
                            '추출된_날짜': None,
                            '사용된_컬럼': None  # 어떤 컬럼에서 날짜가 추출되었는지 추적
                        })
                        
                        # 진행 상태 표시
                        progress_bar = st.progress(0)
                        total_rows = len(combined_df)
                        
                        # 각 행마다 날짜 추출 시도
                        success_count = 0
                        fail_count = 0
                        fail_examples = []
                        
                        # 변환 결과를 디버깅용으로 저장
                        debug_results = []
                        
                        # 각 행 처리 (선택된 모든 컬럼에 대해 시도)
                        for i, row in combined_df.iterrows():
                            extracted_date = None
                            source_column = None
                            
                            # 선택된 모든 컬럼에 대해 시도
                            for col in date_columns:
                                # 원본 날짜 값
                                orig_date = row[col] if col in row else None
                                
                                if pd.isna(orig_date) or orig_date == "":
                                    continue
                                
                                # 디버깅용 메시지 출력
                                debug_info = f"처리 중: 행 {i}, 컬럼 '{col}', 값: '{orig_date}' (타입: {type(orig_date)})"
                                debug_results.append(debug_info)
                                
                                # 컬럼 특성에 따라 is_period_column 설정
                                is_period_column = False
                                col_lower = str(col).lower()
                                if any(keyword in col_lower for keyword in ['출장기간', '기간', '휴가기간']):
                                    is_period_column = True
                                
                                # 날짜 추출 시도
                                date_result = extract_date(orig_date, is_period_column=is_period_column)
                                
                                # 날짜가 추출되면 저장하고 다음 행으로
                                if date_result is not None:
                                    extracted_date = date_result
                                    source_column = col
                                    debug_results.append(f"  → 변환 성공: {extracted_date} (컬럼: {col})")
                                    break
                                else:
                                    debug_results.append(f"  → 변환 실패 (컬럼: {col})")
                            
                            # 결과 저장
                            if extracted_date is not None:
                                result_df.at[i, '추출된_날짜'] = extracted_date
                                result_df.at[i, '사용된_컬럼'] = source_column
                                success_count += 1
                            else:
                                fail_count += 1
                                if len(fail_examples) < 5:
                                    fail_examples.append(row['원본_날짜'])
                            
                            # 진행 상태 업데이트
                            progress_bar.progress(min((i + 1) / total_rows, 1.0))
                        
                        # 디버깅 정보 (토글로 숨겨서 표시)
                        with st.expander("변환 과정 디버깅 정보"):
                            for debug_line in debug_results:
                                st.write(debug_line)
                        
                        # 추출 결과 통계 표시
                        st.write(f"날짜 추출 결과: 성공 {success_count}건, 실패 {fail_count}건")
                        
                        # 컬럼별 추출 성공 통계
                        if success_count > 0:
                            st.write("### 컬럼별 날짜 추출 성공 건수")
                            column_stats = result_df['사용된_컬럼'].value_counts()
                            st.dataframe(pd.DataFrame({
                                '컬럼명': column_stats.index,
                                '추출 성공 건수': column_stats.values
                            }))
                        
                        # 실패한 예시 표시
                        if fail_count > 0:
                            st.warning("처리에 실패한 날짜 예시:")
                            for example in fail_examples:
                                st.write(f"- {example}")
                        
                        # 날짜 변환 결과를 표시 형식으로 변환
                        result_df['추출된_날짜_문자열'] = result_df['추출된_날짜'].apply(
                            lambda x: x.strftime('%Y-%m-%d') if pd.notnull(x) else ''
                        )
                        
                        # 처리 과정을 보여주기 위해 변환 결과 표시
                        st.write("### 날짜 변환 결과 확인")
                        st.dataframe(result_df[['원본_날짜', '추출된_날짜_문자열', '사용된_컬럼']])
                        
                        # 변환 결과 확인 버튼으로 다음 단계로 진행
                        if st.button("날짜 변환 결과 확인 완료", key="confirm_conversion"):
                            # 추출된 날짜를 combined_df에 복사
                            combined_df['날짜'] = result_df['추출된_날짜']
                            
                            # 날짜가 None인 행 제거
                            invalid_rows = combined_df[combined_df['날짜'].isna()]
                            if len(invalid_rows) > 0:
                                st.warning(f"{len(invalid_rows)}개의 날짜를 처리할 수 없어 제외합니다.")
                            
                            combined_df = combined_df.dropna(subset=['날짜'])
                            
                            # 중복 날짜 제거
                            existing_dates = set(combined_df['날짜'])
                            
                            # 결과 단계로 세션 상태 업데이트
                            st.session_state.processing_step = 'results'
                            st.session_state.existing_dates = existing_dates
                            st.session_state.school_code = school_code
                            
                            # Firebase에 상태 업데이트 (다른 사용자에게 알림)
                            if firebase_available:
                                update_session_state("results")
                            
                            # 결과 표시를 위해 페이지 재로드
                            st.rerun()
                    
                    # 결과 표시 단계
                    elif st.session_state.processing_step == 'results':
                        # 저장된 데이터 사용
                        existing_dates = st.session_state.existing_dates
                        school_code = st.session_state.school_code
                        
                        # 처리된 날짜 목록 표시
                        st.write("### 처리된 날짜 목록")
                        
                        # 표로 볼 수 있게 표시
                        date_df = pd.DataFrame(sorted(list(existing_dates)), columns=['날짜'])
                        date_df['요일'] = date_df['날짜'].apply(lambda x: ['월', '화', '수', '목', '금', '토', '일'][x.weekday()])
                        date_df['표시_날짜'] = date_df['날짜'].apply(format_date)
                        
                        st.write(f"총 {len(existing_dates)}개의 고유한 날짜가 발견되었습니다:")
                        st.dataframe(date_df[['표시_날짜', '요일']])
                        
                        # 이용 가능한 날짜 계산
                        available_days_df = process_dates(existing_dates, school_code)
                        
                        # 결과 표시
                        st.subheader("데이터 처리 결과")
                        
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            st.write("### 업로드된 데이터의 날짜")
                            st.dataframe(date_df[['표시_날짜', '요일']])
                            
                            # 날짜 개수 표시
                            st.info(f"총 {len(date_df)}개의 날짜가 발견되었습니다.")
                        
                        with col2:
                            st.write("### 이용 가능한 날짜")
                            # 날짜 표시 형식 변경
                            available_days_df['표시_날짜'] = available_days_df['날짜'].dt.date.apply(format_date)
                            st.dataframe(available_days_df[['표시_날짜', '요일']])
                            
                            # 가용 날짜 개수 표시
                            st.info(f"총 {len(available_days_df)}개의 이용 가능한 날짜가 있습니다.")

                        # 월별 통계 (현재 학년도 데이터 사용)
                        st.write("### 월별 이용 가능한 날짜 수")
                        monthly_stats = available_days_df['날짜'].dt.to_period('M').value_counts().sort_index()
                        monthly_stats.index = monthly_stats.index.strftime('%Y-%m')
                        st.bar_chart(monthly_stats)
                        
                        # 요일별 통계
                        st.write("### 요일별 이용 가능한 날짜 수")
                        weekday_stats = available_days_df['요일'].value_counts()
                        st.bar_chart(weekday_stats)
                        
                        # 엑셀 파일로 저장
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                            # 업로드된 날짜 정보를 포함한 데이터프레임 저장
                            date_df.to_excel(writer, sheet_name='업로드된 날짜', index=False)
                            
                            # 이용 가능한 날짜 정보를 포함한 데이터프레임 저장
                            available_days_df.to_excel(writer, sheet_name='이용 가능한 날짜', index=False)
                        
                        output.seek(0)
                        
                        st.download_button(
                            label=f"{school_info['SCHUL_NM']} 데이터 다운로드",
                            data=output,
                            file_name=f"{school_info['SCHUL_NM']}_processed_data.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                        
                        # 새로운 처리 시작 버튼
                        if st.button("새로운 데이터 처리", key="new_processing"):
                            st.session_state.processing_step = 'start'
                            # Firebase 상태 초기화
                            if firebase_available:
                                update_session_state("start")
                            st.rerun()
        else:
            st.warning("처리할 데이터가 없습니다. 먼저 파일을 업로드해주세요.")

elif selected_project == '프로젝트 2':
    st.title('프로젝트 2')
    st.write('자동화 했으면 하는 업무 있으실까요?')

elif selected_project == '프로젝트 3':
    st.title('프로젝트 3')
    st.write('이거 매번 하는 거 귀찮았는데 하는 거 있으셨나요?')
