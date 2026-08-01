# ---- Stage 1: Build ----
FROM python:3.11-slim AS builder

WORKDIR /app

# Tạo môi trường ảo trong /app/venv
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Stage 2: Production ----
FROM python:3.11-slim

WORKDIR /app

# Tạo non-root user trước
RUN useradd -m appuser

# Copy toàn bộ virtual environment từ builder sang
COPY --from=builder /app/venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Copy mã nguồn ứng dụng
COPY . .

# Tạo thư mục data và phân quyền toàn bộ thư mục /app cho appuser
RUN mkdir -p /app/data /app/snapshots && chown -R appuser:appuser /app

# Chuyển sang chạy bằng non-root user
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]