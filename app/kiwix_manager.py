import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from app.config_parser import invalidate_zim_scan_cache

logger = logging.getLogger("prepper.kiwix")


class KiwixManager:
    """
    Docker içinde kiwix-manage ile library.xml oluşturur ve
    kiwix-serve sürecini arka planda yönetir.
    Hiç .zim dosyası yokken kiwix-serve'in hata verip çökmesini önler.
    """

    def __init__(self, zim_dir: Path, library_xml: Path, port: int = 8081):
        self.zim_dir = zim_dir
        self.library_xml = library_xml
        self.port = port
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    @property
    def has_kiwix_binaries(self) -> bool:
        return shutil.which("kiwix-serve") is not None

    def is_running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def get_zim_files(self) -> list[Path]:
        if not self.zim_dir.exists():
            return []
        return sorted(p for p in self.zim_dir.glob("*.zim") if p.is_file())

    def rebuild_library_and_reload(self) -> bool:
        """
        /library/zims/content içindeki .zim dosyalarını tarar,
        library.xml dosyasını günceller ve kiwix-serve sürecini yeniden başlatır.
        """
        with self._lock:
            invalidate_zim_scan_cache()
            zim_files = self.get_zim_files()
            self._stop_locked()

            if not zim_files:
                if self.library_xml.exists():
                    try:
                        self.library_xml.unlink()
                    except OSError:
                        pass
                logger.info("Hiç .zim dosyası bulunamadı; kiwix-serve beklemede.")
                return False

            if not self.has_kiwix_binaries:
                logger.warning("kiwix-serve ikili dosyası bulunamadı (Docker dışı ortam). Katalog emülasyonu aktif.")
                return False

            self.library_xml.parent.mkdir(parents=True, exist_ok=True)
            fast_tmp_xml = Path(tempfile.gettempdir()) / "prepper_library.xml"
            if fast_tmp_xml.exists():
                fast_tmp_xml.unlink()

            kiwix_manage_bin = shutil.which("kiwix-manage")
            use_library_xml = False

            if kiwix_manage_bin:
                res = subprocess.run(
                    [kiwix_manage_bin, str(fast_tmp_xml), "add", *[str(z) for z in zim_files]],
                    capture_output=True,
                    text=True,
                )
                if res.returncode == 0 and fast_tmp_xml.exists():
                    use_library_xml = True
                else:
                    logger.error("kiwix-manage hatası: %s", res.stderr)

            if use_library_xml and fast_tmp_xml.exists():
                try:
                    shutil.copyfile(fast_tmp_xml, self.library_xml)
                except OSError:
                    pass
                cmd = [
                    "kiwix-serve",
                    f"--port={self.port}",
                    "--urlRootLocation=/kiwix",
                    "--library",
                    str(fast_tmp_xml),
                ]
            else:
                cmd = [
                    "kiwix-serve",
                    f"--port={self.port}",
                    "--urlRootLocation=/kiwix",
                    *[str(z) for z in zim_files],
                ]

            try:
                logger.info("kiwix-serve başlatılıyor (%d ZIM): %s", len(zim_files), " ".join(cmd))
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                time.sleep(0.3)
                if self._process.poll() is not None:
                    err = self._process.stderr.read().decode("utf-8", errors="replace") if self._process.stderr else ""
                    logger.error("kiwix-serve başlatılamadı: %s", err)
                    return False
                return True
            except Exception as exc:
                logger.exception("kiwix-serve başlatılırken hata: %s", exc)
                return False

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self._process is not None:
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            self._process = None
