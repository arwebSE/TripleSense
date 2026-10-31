FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    libegl1 libgl1 libudev-dev libevdev-dev libxcb-cursor0 gcc libc6-dev dpkg-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /source
ENV QT_QPA_PLATFORM=offscreen
COPY . /source
RUN python -m pip install --no-cache-dir -e '.[controller,app,dev,build]' \
    && ruff check src tests tools \
    && ruff format --check src tests tools \
    && python -m unittest discover -s tests -t . \
    && python tools/build_app.py
