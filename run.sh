#!/bin/bash
set -e

cd "$(dirname "$0")"

if [ -x "/Users/bongbong/workspace/prompt_injection_game/venv/bin/uvicorn" ]; then
  UVICORN_BIN="/Users/bongbong/workspace/prompt_injection_game/venv/bin/uvicorn"
else
  if [ ! -d "venv" ]; then
    echo "📦 Python 가상환경(venv) 생성 중..."
    python3 -m venv venv
  fi
  source venv/bin/activate
  pip install -q -r requirements.txt
  UVICORN_BIN="uvicorn"
fi

echo "========================================================"
echo "🎲 《데블스 플랜 3》 히든 워드 멀티플레이어 서버 시작!"
echo "👉 브라우저 접속: http://localhost:8080"
echo "👉 초대 링크 예시: http://localhost:8080/?room=DP3GO"
echo "========================================================"

exec "$UVICORN_BIN" app:app --host 0.0.0.0 --port 8080 --reload
