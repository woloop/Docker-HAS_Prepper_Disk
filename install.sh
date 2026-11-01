#!/usr/bin/env bash
# HAS_PrepperDisk (Docker & Web Sürümü) başlatıcı betiği / starter script
# Not: Eski Internet-in-a-Box (IIAB) ve Hotspot kurulum betiği legacy/install-iiab.sh altındadır.
# Note: The legacy Internet-in-a-Box (IIAB) installer is preserved in legacy/install-iiab.sh.
#
# Kullanım / usage:  ./install.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO"

say(){ printf '\n\033[1m== %s\033[0m\n' "$*"; }
die(){ echo "HATA / ERROR: $*" >&2; exit 1; }

say "1/2 Kontroller / Checks"
command -v docker >/dev/null 2>&1 || die "Docker kurulu değil / Docker is not installed: https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || die "Docker Compose kurulu değil / Docker Compose plugin is not installed"

mkdir -p "$REPO/library/zims/content" "$REPO/library/config"

say "2/2 HAS_PrepperDisk Docker konteyneri başlatılıyor / Starting container"
docker compose up -d --build

IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
PORT="${PREPPER_PORT:-7572}"

say "Hazır / Ready!"
cat <<EOF
Kurulum Sihirbazı & Paket Yönetimi / Setup Wizard:  http://${IP}:${PORT}/setup
Ana Sayfa / Offline Homepage:                       http://${IP}:${PORT}/home
Kiwix Kütüphanesi / Kiwix Library:                  http://${IP}:${PORT}/kiwix/
EOF
