import asyncio
import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
import httpx

logger = logging.getLogger("prepper.downloader")

KIWIX_BASE_URL = "https://download.kiwix.org/zim"


def format_bytes(num_bytes: float) -> str:
    if num_bytes < 1024:
        return f"{int(num_bytes)} B"
    for unit in ["KB", "MB", "GB", "TB"]:
        num_bytes /= 1024.0
        if num_bytes < 1024.0:
            return f"{num_bytes:.1f} {unit}"
    return f"{num_bytes:.1f} PB"


class DownloadManager:
    """
    Paralel (eşzamanlı çoklu) ZIM sürüm çözümleme, .part uzantılı kesintisiz
    (resumable) indirme ve eski sürüm temizleme işlemlerini asenkron olarak yürüten motor.
    """

    def __init__(
        self,
        zim_dir: Path,
        on_package_complete: Optional[Callable[[], Any]] = None,
        max_concurrent: int = 3,
    ):
        self.zim_dir = zim_dir
        self.on_package_complete = on_package_complete
        self.max_concurrent = max(1, min(max_concurrent, 8))

        self.queue: List[Dict[str, str]] = []
        self.active_downloads: Dict[str, Dict[str, Any]] = {}
        self.history: List[Dict[str, Any]] = []

        self._cancelled_prefixes: Dict[str, bool] = {}  # prefix -> delete_partial
        self._cancel_all = False
        self._cancel_all_delete = False
        self._worker_tasks: List[asyncio.Task] = []
        self._lock = asyncio.Lock()
        self._folder_cache: Dict[str, tuple[float, str]] = {}
        self._folder_locks: Dict[str, asyncio.Lock] = {}

    def get_status(self) -> Dict[str, Any]:
        active_list = list(self.active_downloads.values())
        total_speed = sum(a.get("speed_bps", 0) for a in active_list)
        return {
            "is_running": len(active_list) > 0 or len(self.queue) > 0,
            "max_concurrent": self.max_concurrent,
            "active_count": len(active_list),
            "active_downloads": active_list,
            "active": active_list[0] if active_list else None,
            "total_speed_bps": total_speed,
            "total_speed_human": f"{format_bytes(total_speed)}/s" if total_speed > 0 else "—",
            "queue": list(self.queue),
            "history": self.history[-25:],
        }

    async def set_concurrency(self, max_concurrent: int) -> Dict[str, Any]:
        async with self._lock:
            self.max_concurrent = max(1, min(int(max_concurrent), 8))
            self._ensure_workers_locked()
        return self.get_status()

    def _ensure_workers_locked(self) -> None:
        # Tamamlanmış görevleri temizle
        self._worker_tasks = [t for t in self._worker_tasks if not t.done()]
        # Kuyrukta iş varsa max_concurrent sayısına kadar paralel işçi başlat
        needed = min(len(self.queue) + len(self.active_downloads), self.max_concurrent) - len(self._worker_tasks)
        for _ in range(max(0, needed)):
            self._worker_tasks.append(asyncio.create_task(self._worker_loop()))

    async def enqueue(self, items: List[Dict[str, str]], max_concurrent: Optional[int] = None) -> Dict[str, Any]:
        """
        Seçilen paketleri indirme kuyruğuna ekler ve paralel işçileri başlatır.
        """
        async with self._lock:
            if max_concurrent is not None:
                self.max_concurrent = max(1, min(int(max_concurrent), 8))

            existing_prefixes = {q["prefix"] for q in self.queue} | set(self.active_downloads.keys())

            added = []
            for item in items:
                prefix = item["prefix"]
                if prefix not in existing_prefixes:
                    self._cancelled_prefixes.pop(prefix, None)
                    self.queue.append({
                        "prefix": prefix,
                        "folder": item["folder"],
                        "name": item.get("name", prefix),
                    })
                    existing_prefixes.add(prefix)
                    added.append(prefix)

            self._cancel_all = False
            self._ensure_workers_locked()

        return {"added": added, "queue_length": len(self.queue)}

    async def cancel(self, prefix: Optional[str] = None, delete_partial: bool = False) -> Dict[str, Any]:
        """
        Belirli bir paketi veya tüm paralel indirmeleri durdurur.
        """
        async with self._lock:
            if prefix is None:
                self.queue.clear()
                self._cancel_all = True
                self._cancel_all_delete = delete_partial
                for p in list(self.active_downloads.keys()):
                    self._cancelled_prefixes[p] = delete_partial
                return {"status": "cancelling_all"}

            # Kuyruktaysa çıkar
            before = len(self.queue)
            self.queue = [q for q in self.queue if q["prefix"] != prefix]
            if len(self.queue) < before:
                if delete_partial:
                    self._delete_part_files(prefix)
                return {"status": "removed_from_queue", "prefix": prefix}

            # Aktif indirilenler arasındaysa iptal sinyali işaretle
            if prefix in self.active_downloads:
                self._cancelled_prefixes[prefix] = delete_partial
                return {"status": "cancelling_active", "prefix": prefix}

        if delete_partial and prefix:
            self._delete_part_files(prefix)

        return {"status": "not_found", "prefix": prefix}

    def _delete_part_files(self, prefix: str) -> None:
        for part_file in self.zim_dir.glob(f"{prefix}_*.zim.part"):
            try:
                part_file.unlink()
            except OSError:
                pass

    async def resolve_latest_filename(self, client: httpx.AsyncClient, folder: str, prefix: str) -> Optional[str]:
        if folder not in self._folder_locks:
            self._folder_locks[folder] = asyncio.Lock()

        async with self._folder_locks[folder]:
            now = time.monotonic()
            cached = self._folder_cache.get(folder)
            if cached and (now - cached[0] < 600.0):
                html_text = cached[1]
            else:
                url = f"{KIWIX_BASE_URL}/{folder}/"
                resp = await client.get(url, timeout=30.0)
                resp.raise_for_status()
                html_text = resp.text
                self._folder_cache[folder] = (now, html_text)

        pattern = re.compile(rf"({re.escape(prefix)}_\d{{4}}-\d{{2}}[a-z]?\.zim)")
        matches = sorted(set(pattern.findall(html_text)))
        return matches[-1] if matches else None

    async def _worker_loop(self) -> None:
        self.zim_dir.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(60.0, connect=20.0)) as client:
            while True:
                async with self._lock:
                    # Eşzamanlı sınır düşürüldüyse ve fazla işçi varsa çık
                    if len(self.active_downloads) >= self.max_concurrent:
                        break
                    if not self.queue or self._cancel_all:
                        break
                    current_item = self.queue.pop(0)
                    prefix = current_item["prefix"]
                    folder = current_item["folder"]
                    name = current_item["name"]
                    self._cancelled_prefixes.pop(prefix, None)

                    state = {
                        "prefix": prefix,
                        "folder": folder,
                        "name": name,
                        "filename": None,
                        "stage": "resolving",
                        "downloaded_bytes": 0,
                        "total_bytes": 0,
                        "percent": 0.0,
                        "speed_bps": 0,
                        "speed_human": "—",
                        "eta_seconds": None,
                        "message": "Kiwix sunucusundan en güncel sürüm kontrol ediliyor...",
                    }
                    self.active_downloads[prefix] = state

                try:
                    latest = await self.resolve_latest_filename(client, folder, prefix)
                    if not latest:
                        self._record_history(prefix, name, "error", f"{folder}/{prefix} Kiwix sunucusunda bulunamadı.")
                        continue

                    state["filename"] = latest
                    dest_file = self.zim_dir / latest
                    part_file = self.zim_dir / f"{latest}.part"

                    if dest_file.exists():
                        self._record_history(prefix, name, "completed", f"{latest} zaten kurulu.")
                        if self.on_package_complete:
                            await asyncio.to_thread(self.on_package_complete)
                        continue

                    max_retries = 5
                    for attempt in range(1, max_retries + 1):
                        try:
                            await self._download_file(client, state, folder, latest, dest_file, part_file)
                            break
                        except httpx.HTTPError as net_exc:
                            if prefix in self._cancelled_prefixes or self._cancel_all or attempt == max_retries:
                                raise
                            logger.warning(
                                "Bağlantı kesildi (%s, deneme %d/%d): %s — 2 sn içinde kaldığı yerden devam ediliyor...",
                                prefix, attempt, max_retries, net_exc,
                            )
                            state["message"] = f"Bağlantı yenileniyor (deneme {attempt}/{max_retries})..."
                            await asyncio.sleep(2.0)

                except asyncio.CancelledError:
                    self._record_history(prefix, name, "paused", "İndirme duraklatıldı.")
                    break
                except Exception as exc:
                    logger.exception("İndirme hatası (%s): %s", prefix, exc)
                    self._record_history(prefix, name, "error", f"Hata: {exc}")
                finally:
                    async with self._lock:
                        self.active_downloads.pop(prefix, None)
                        self._cancelled_prefixes.pop(prefix, None)
                        if not self.queue and not self.active_downloads:
                            self._cancel_all = False

    async def _download_file(
        self,
        client: httpx.AsyncClient,
        state: Dict[str, Any],
        folder: str,
        latest: str,
        dest_file: Path,
        part_file: Path,
    ) -> None:
        prefix = state["prefix"]
        name = state["name"]
        file_url = f"{KIWIX_BASE_URL}/{folder}/{latest}"

        resume_bytes = part_file.stat().st_size if part_file.exists() else 0
        headers = {"Range": f"bytes={resume_bytes}-"} if resume_bytes > 0 else {}

        state["stage"] = "downloading"
        state["downloaded_bytes"] = resume_bytes
        state["message"] = (
            f"Kaldığı yerden devam ediliyor ({format_bytes(resume_bytes)})..."
            if resume_bytes > 0
            else "İndiriliyor..."
        )

        async with client.stream("GET", file_url, headers=headers) as resp:
            if resp.status_code == 416:
                part_file.unlink(missing_ok=True)
                resume_bytes = 0
                headers = {}

            if resp.status_code not in (200, 206):
                resp.raise_for_status()

            is_resumed = resp.status_code == 206
            if not is_resumed:
                resume_bytes = 0

            content_length = int(resp.headers.get("Content-Length", 0))
            total_bytes = (resume_bytes + content_length) if content_length > 0 else 0
            state["total_bytes"] = total_bytes

            mode = "ab" if is_resumed else "wb"
            downloaded = resume_bytes
            last_tick = time.monotonic()
            bytes_since_tick = 0
            smoothed_speed = 0.0
            write_buf = bytearray()

            with open(part_file, mode) as f:
                async for chunk in resp.aiter_bytes(chunk_size=256 * 1024):
                    if prefix in self._cancelled_prefixes or self._cancel_all:
                        if write_buf:
                            await asyncio.to_thread(f.write, bytes(write_buf))
                            write_buf.clear()
                        f.flush()
                        del_part = self._cancelled_prefixes.get(prefix, self._cancel_all_delete)
                        if del_part:
                            try:
                                part_file.unlink(missing_ok=True)
                            except OSError:
                                pass
                            self._record_history(prefix, name, "cancelled", "İndirme iptal edildi ve geçici dosya silindi.")
                        else:
                            self._record_history(
                                prefix,
                                name,
                                "paused",
                                f"Duraklatıldı ({format_bytes(downloaded)} indi, devam ettirilebilir).",
                            )
                        return

                    write_buf.extend(chunk)
                    if len(write_buf) >= 2 * 1024 * 1024:
                        payload = bytes(write_buf)
                        write_buf.clear()
                        await asyncio.to_thread(f.write, payload)

                    chunk_len = len(chunk)
                    downloaded += chunk_len
                    bytes_since_tick += chunk_len

                    now = time.monotonic()
                    elapsed = now - last_tick
                    if elapsed >= 0.4:
                        inst_speed = bytes_since_tick / elapsed
                        smoothed_speed = inst_speed if smoothed_speed == 0 else (0.7 * smoothed_speed + 0.3 * inst_speed)
                        last_tick = now
                        bytes_since_tick = 0

                        percent = round((downloaded / total_bytes) * 100, 1) if total_bytes > 0 else 0.0
                        eta = int((total_bytes - downloaded) / smoothed_speed) if (smoothed_speed > 0 and total_bytes > downloaded) else None

                        state.update({
                            "downloaded_bytes": downloaded,
                            "total_bytes": total_bytes,
                            "percent": min(percent, 100.0),
                            "speed_bps": int(smoothed_speed),
                            "speed_human": f"{format_bytes(smoothed_speed)}/s",
                            "eta_seconds": eta,
                            "message": f"{format_bytes(downloaded)} / {format_bytes(total_bytes)}" if total_bytes else format_bytes(downloaded),
                        })

                if write_buf:
                    await asyncio.to_thread(f.write, bytes(write_buf))
                    write_buf.clear()

        state["stage"] = "finalizing"
        state["percent"] = 100.0
        state["message"] = "SHA-256 bütünlüğü kontrol ediliyor..."

        # SHA-256 Doğrulama (Kiwix .sha256 kontrolü)
        sha_url = f"{file_url}.sha256"
        expected_sha = None
        try:
            sha_resp = await client.get(sha_url)
            if sha_resp.status_code == 200:
                first_token = sha_resp.text.strip().split()[0].lower() if sha_resp.text.strip() else ""
                if re.match(r"^[0-9a-f]{64}$", first_token):
                    expected_sha = first_token
        except Exception as exc:
            logger.warning("%s için .sha256 çekilemedi: %s", latest, exc)

        if expected_sha:
            def _calc_sha(path: Path) -> str:
                h = hashlib.sha256()
                with open(path, "rb") as sf:
                    while chunk := sf.read(1024 * 1024):
                        h.update(chunk)
                return h.hexdigest().lower()

            actual_sha = await asyncio.to_thread(_calc_sha, part_file)
            if actual_sha != expected_sha:
                logger.error("%s SHA-256 uyuşmazlığı! Beklenen: %s, Bulunan: %s", latest, expected_sha, actual_sha)
                try:
                    part_file.unlink(missing_ok=True)
                except OSError:
                    pass
                self._record_history(
                    prefix,
                    name,
                    "error",
                    f"SHA-256 doğrulama hatası! Dosya bozuk indirildi ve silindi (beklenen: {expected_sha[:8]}..., bulunan: {actual_sha[:8]}...)",
                )
                return
            logger.info("%s SHA-256 doğrulandı (OK: %s)", latest, actual_sha)

        state["message"] = "Kiwix kütüphanesine ekleniyor..."
        part_file.replace(dest_file)

        for old_zim in self.zim_dir.glob(f"{prefix}_*.zim"):
            if old_zim != dest_file and old_zim.is_file():
                try:
                    logger.info("Eski ZIM sürümü siliniyor: %s", old_zim.name)
                    old_zim.unlink()
                except OSError:
                    pass

        if self.on_package_complete:
            await asyncio.to_thread(self.on_package_complete)

        self._record_history(prefix, name, "completed", f"{latest} başarıyla kuruldu ({format_bytes(dest_file.stat().st_size)}).")

    def _record_history(self, prefix: str, name: str, status: str, message: str) -> None:
        self.history.append({
            "prefix": prefix,
            "name": name,
            "status": status,
            "message": message,
            "timestamp": int(time.time()),
        })
