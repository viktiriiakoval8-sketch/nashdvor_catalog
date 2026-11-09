FROM python:3.12-slim
WORKDIR /app
COPY facade/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt tzdata
COPY . .
RUN useradd --create-home facade && mkdir -p /data && chown facade:facade /data
USER facade
ENV FACADE_DATA_DIR=/data HF_HOME=/data/model-cache
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "facade.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
