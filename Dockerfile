FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libx11-6 \
    libxext6 \
    libxrender1 \
    libsm6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . /app
RUN pip install -e . \
 && pip install --no-deps -e vendor/restoration-common \
 && pip install waitress gunicorn

RUN useradd -m -u 1000 toolbox || true
USER 1000

ENV TOOLBOX_DATA_DIR=/data \
    TOOLBOX_UPLOAD_DIR=/data/uploads \
    TOOLBOX_ATTACHMENTS_DIR=/data/attachments

EXPOSE 8777

CMD ["python", "-m", "waitress", "--host=0.0.0.0", "--port=8777", "--threads=4", "--call", "toolbox.app:create_app"]
