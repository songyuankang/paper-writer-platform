FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

COPY paper_writer_scripts ./paper_writer_scripts

ENV PAPER_WRITER_SCRIPTS_DIR=/app/paper_writer_scripts
ENV PAPER_WRITER_UPLOAD_DIR=/app/uploads
ENV PAPER_WRITER_OUTPUT_DIR=/app/outputs
ENV PAPER_WRITER_LOG_DIR=/app/logs

VOLUME ["/app/uploads", "/app/outputs", "/app/logs"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
