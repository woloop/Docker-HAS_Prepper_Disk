#!/usr/bin/env bash
# config/content.conf içindeki ZIM dosyalarının en yeni sürümünü indirir ve Kiwix'e ekler.
# Downloads the newest version of each ZIM in config/content.conf and adds it to Kiwix.
# Not: Bu işlemi Web arayüzünden (/setup) görsel olarak da yapabilirsiniz.
# Note: You can also perform this visually from the Web Setup Wizard (/setup).
#
# Kullanım / usage:  ./scripts/download-content.sh [config-dosyası]
set -uo pipefail

CONF="${1:-$(cd "$(dirname "$0")/.." && pwd)/config/content.conf}"
DEST="${PREPPER_ZIM_DIR:-/library/zims/content}"
LIB_XML="${PREPPER_LIBRARY_XML:-/library/zims/library.xml}"
BASE=https://download.kiwix.org/zim

mkdir -p "$DEST"

failed=0
while read -r folder prefix _; do
  case "$folder" in ''|\#*) continue;; esac

  latest=$(curl -fsSL "$BASE/$folder/" | grep -oE "${prefix}_[0-9]{4}-[0-9]{2}[a-z]?\.zim" | sort -u | tail -1)
  if [ -z "$latest" ]; then echo "!! $prefix bulunamadı / not found in $BASE/$folder/"; failed=1; continue; fi

  if [ -f "$DEST/$latest" ]; then echo "== $latest zaten var / already present"; continue; fi

  echo ">> $latest indiriliyor / downloading"
  df -h "$DEST" | tail -1
  if wget -c --progress=dot:giga -O "$DEST/$latest.part" "$BASE/$folder/$latest" < /dev/null; then
    mv "$DEST/$latest.part" "$DEST/$latest"
    echo "OK $latest tamamlandı / done"
    # Eski sürümleri sil / remove older versions of the same ZIM
    for old in "$DEST/${prefix}"_*.zim; do
      [ "$old" != "$DEST/$latest" ] && [ -f "$old" ] && { echo "-- eski sürüm siliniyor / removing $old"; rm -f "$old"; }
    done
  else
    echo "!! $latest indirilemedi / download failed (tekrar çalıştır / re-run to resume)"; failed=1
  fi
done < "$CONF"

echo ">> Kiwix kütüphanesi güncelleniyor / rebuilding Kiwix library"
if command -v iiab-make-kiwix-lib >/dev/null 2>&1; then
  iiab-make-kiwix-lib
elif command -v kiwix-manage >/dev/null 2>&1; then
  rm -f "$LIB_XML"
  shopt -s nullglob
  for zim in "$DEST"/*.zim; do
    kiwix-manage "$LIB_XML" add "$zim"
  done
  echo "OK Kiwix library.xml güncellendi / updated: $LIB_XML"
else
  echo "!! kiwix-manage veya iiab-make-kiwix-lib bulunamadı / not found."
fi

exit $failed
