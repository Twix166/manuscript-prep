FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && addgroup --system manuscriptprep \
    && adduser --system --ingroup manuscriptprep --home /app manuscriptprep

COPY . /app
RUN chown -R manuscriptprep:manuscriptprep /app

ENTRYPOINT ["/bin/sh", "/app/docker-entrypoint.sh"]

CMD ["python", "manuscriptprep_gateway_api.py", "--host", "0.0.0.0", "--port", "8765"]
