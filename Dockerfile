FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 WORKSHOP_STANDALONE=1
RUN apt-get update && apt-get install -y --no-install-recommends default-jre-headless poppler-utils tesseract-ocr tesseract-ocr-eng fontconfig fonts-liberation2 fonts-dejavu-core fonts-noto-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY scripts scripts
RUN python scripts/install_verapdf.py
ENV PATH="/opt/verapdf:${PATH}" JAVA_OPTS="-Xmx512m"
COPY workshop workshop
COPY web web
COPY LICENSE THIRD_PARTY_NOTICES.md ./
RUN python scripts/dependency_inventory.py > /app/runtime-dependencies.json
RUN useradd --create-home workshop
USER workshop
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--timeout", "240", "web.app:app"]
