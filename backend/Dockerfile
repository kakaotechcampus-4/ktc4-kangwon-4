# RE:BORN backend — 배포용 컨테이너 이미지 (BE기술스택.html §5, BE 실제 테스트 완료본).

FROM python:3.12-slim

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app ./app

# 서류 OCR(#128)이 쓰는 한국어·영어 언어 파일. 요청마다 내려받지 않게 이미지를 만들 때 한 번 받아 둔다.
# 서류 원본·가린 PDF·Case별 목록은 AGENT_DOCUMENT_DIR에 쌓이므로 compose에서 볼륨으로 남긴다.
COPY ./scripts/setup_agent_ocr.py ./scripts/setup_agent_ocr.py
RUN python scripts/setup_agent_ocr.py --directory /opt/reborn/tessdata
ENV AGENT_OCR_TESSDATA_DIR=/opt/reborn/tessdata \
    AGENT_DOCUMENT_DIR=/data/documents

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
