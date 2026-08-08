FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# paper-writer skill 脚本目录（运行时模块导入，不复制生成代码）。
# 容器内通过挂载卷提供，见 README「Docker 运行」。
ENV PAPER_WRITER_SCRIPTS_DIR=/app/paper_writer_scripts
ENV PAPER_WRITER_UPLOAD_DIR=/app/uploads
ENV PAPER_WRITER_OUTPUT_DIR=/app/outputs
ENV PAPER_WRITER_LOG_DIR=/app/logs

VOLUME ["/app/uploads", "/app/outputs", "/app/logs", "/app/paper_writer_scripts"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
