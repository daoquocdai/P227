FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# InsightFace needs a compiler while its wheel is being built. PyTorch is
# installed explicitly from the official CPU index so this image never pulls
# CUDA libraries.
RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt ./
COPY requirements ./requirements
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r requirements/vision-cpu.txt


FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    VISION_DEVICE=cpu \
    VISION_IDENTITY_PROVIDER=cpu \
    HOME=/home/appuser

WORKDIR /app

# Runtime libraries used by OpenCV, MediaPipe and the CPU inference stack.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

COPY --from=builder /opt/venv /opt/venv
COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser database ./database

RUN mkdir -p /app/data /app/snapshots /home/appuser/.insightface \
    && chown -R appuser:appuser /app/data /app/snapshots /home/appuser/.insightface

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)"

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
