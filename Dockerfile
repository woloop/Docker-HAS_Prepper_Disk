FROM python:3.11-slim-bookworm

LABEL maintainer="HAS_Prepper_Disk Fork"
LABEL description="Offline Digital Survival Library with Web Setup Wizard & Kiwix"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PREPPER_PORT=7572 \
    KIWIX_PORT=8081 \
    PREPPER_LIBRARY_DIR=/library \
    PREPPER_ZIM_DIR=/library/zims/content \
    PREPPER_LIBRARY_XML=/library/zims/library.xml

# Install kiwix-tools (kiwix-serve & kiwix-manage) and download utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    kiwix-tools \
    curl \
    wget \
    ca-certificates \
    tar \
    && rm -rf /var/lib/apt/lists/*

# Install pmtiles CLI for offline vector map extraction
RUN ARCH=$(uname -m) && \
    case "$ARCH" in \
        x86_64) PM_ARCH="x86_64" ;; \
        aarch64|arm64) PM_ARCH="arm64" ;; \
        armv7l) PM_ARCH="armv7" ;; \
        *) PM_ARCH="x86_64" ;; \
    esac && \
    curl -fsSL "https://github.com/protomaps/go-pmtiles/releases/download/v1.22.1/go-pmtiles_1.22.1_Linux_${PM_ARCH}.tar.gz" | tar -xz -C /usr/local/bin pmtiles && \
    chmod +x /usr/local/bin/pmtiles || true

WORKDIR /opt/prepper

# Install Python dependencies first for layer caching
COPY app/requirements.txt /opt/prepper/app/requirements.txt
RUN pip install --no-cache-dir -r /opt/prepper/app/requirements.txt

# Copy project files
COPY config/ /opt/prepper/config/
COPY scripts/ /opt/prepper/scripts/
COPY www/ /opt/prepper/www/
COPY app/ /opt/prepper/app/

# Create persistent library directory structure
RUN mkdir -p /library/zims/content /library/config && \
    chmod +x /opt/prepper/scripts/*.sh

VOLUME ["/library"]

EXPOSE 7572

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7572"]
