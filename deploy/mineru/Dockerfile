FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
ARG DEBIAN_MIRROR=deb.debian.org
RUN sed -i "s|http://deb.debian.org|https://${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
    libgl1 libglib2.0-0 libgomp1 libvulkan1 vulkan-tools ca-certificates fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir "mineru==4.0.12" "mineru-llama-cpp==0.1.3" \
    && python -m pip check

# NVIDIA's Vulkan ICD dynamically loads EGL; it is not pulled in by libgl1.
RUN apt-get -o Acquire::Retries=3 update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends libegl1 libgbm1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 mineru \
    && mkdir -p /data/home /data/uploads /data/results \
    && chown -R mineru:mineru /data
WORKDIR /service
COPY serve.py healthcheck.py probe.py /service/
USER mineru
EXPOSE 8000
ENTRYPOINT ["python", "/service/serve.py"]
