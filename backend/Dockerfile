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

# 검수 자료 버전이 바뀌면 기존 Case에 다시 적재하는 명령을 배포 이미지에서도 쓴다.
COPY ./scripts/import_reviewed_procedures.py ./scripts/import_reviewed_procedures.py

# 이 이미지를 빌드한 커밋. /health가 그대로 보여 줘서 서버에 들어가지 않고 운영 버전을 확인한다.
# 배포 명령이 넘긴다(docs/deploy.md). 커밋마다 값이 바뀌므로 맨 아래에 둬서, 위의 패키지 설치·OCR 받기는 캐시를 쓴다.
ARG GIT_SHA=unknown
ENV APP_VERSION=$GIT_SHA

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
