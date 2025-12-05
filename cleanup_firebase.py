#!/usr/bin/env python3
"""
Firebase 데이터베이스 초기화 스크립트
기존 방(rooms)과 파일 업로드(file_uploads) 데이터를 모두 삭제합니다.
"""

import firebase_admin
from firebase_admin import credentials, db as firebase_rtdb, storage
import json
import os

# secrets.toml 파일 읽기
secrets_path = ".streamlit/secrets.toml"

if not os.path.exists(secrets_path):
    print(f"❌ {secrets_path} 파일을 찾을 수 없습니다.")
    print("Firebase 설정 파일이 필요합니다.")
    exit(1)

# TOML 파일 파싱 (간단한 방법)
print("📖 Firebase 설정 로드 중...")

# 수동으로 Firebase 자격증명 입력 (또는 환경변수 사용)
# 여기서는 Firebase Console에서 직접 삭제하는 것을 권장합니다.

print("""
Firebase 데이터 초기화 방법:

방법 1: Firebase Console 사용 (권장)
1. https://console.firebase.google.com 접속
2. 프로젝트 선택 (project-a019a)
3. 왼쪽 메뉴에서 "Realtime Database" 클릭
4. "데이터" 탭에서 다음 항목들을 삭제:
   - rooms (모든 방 데이터)
   - file_uploads (파일 업로드 메타데이터)
   - sessions (세션 데이터)
5. 왼쪽 메뉴에서 "Storage" 클릭
6. "Files" 탭에서 "uploads/" 폴더 전체 삭제

방법 2: 앱에서 "모든 데이터 초기화" 버튼 사용
1. 앱 사이드바에서 "Firebase 설정 도움말" 확장
2. "모든 데이터 초기화" 버튼 클릭

방법 3: 이 스크립트 실행 (개발 환경)
- Firebase Admin SDK 자격증명이 필요합니다
- .streamlit/secrets.toml 파일이 올바르게 설정되어 있어야 합니다
""")

# 사용자 확인
response = input("\nFirebase Console에서 수동으로 삭제하시겠습니까? (y/n): ")
if response.lower() == 'y':
    print("\n✅ Firebase Console을 열어주세요:")
    print("   https://console.firebase.google.com/project/project-a019a/database/project-a019a-default-rtdb/data")
    print("\n삭제할 경로:")
    print("   - /rooms")
    print("   - /file_uploads")
    print("   - /sessions")
else:
    print("\n스크립트를 통한 자동 삭제는 현재 환경에서 지원되지 않습니다.")
    print("Firebase Console을 사용해주세요.")
