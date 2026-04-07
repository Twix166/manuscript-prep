FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ghostscript \
        ocrmypdf \
        poppler-utils \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && addgroup --system manuscriptprep \
    && adduser --system --ingroup manuscriptprep --home /app manuscriptprep

COPY . /app
RUN chown -R manuscriptprep:manuscriptprep /app

ENTRYPOINT ["/bin/sh", "/app/docker-entrypoint.sh"]

CMD ["python", "manuscriptprep_gateway_api.py", "--host", "0.0.0.0", "--port", "8765"]
