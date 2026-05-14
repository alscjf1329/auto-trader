#!/bin/bash

# 루트 폴더로 이동 (bin/linux 기준 두 단계 위)
cd "$(dirname "$0")/../.."

echo "=== 가상환경 설정 ==="

# 가상환경 없으면 생성
if [ ! -d "venv" ]; then
    echo "가상환경 생성 중..."
    python3 -m venv venv
fi

# 가상환경 활성화
source venv/bin/activate

# 라이브러리 설치
echo "라이브러리 설치 중..."
pip install -r requirements.txt

echo "=== 설정 완료 ==="
