# RE:BORN backend — 배포/로컬 공용 컨테이너 이미지 (BE기술스택.html §5, BE 실제 테스트 완료본).
# 전제: backend/app/main.py 에 FastAPI 앱(`app`)이 존재해야 함 (아직 코드 없음 — 스캐폴딩 시 함께 채울 것).

FROM python:3.12-slim

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app ./app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
