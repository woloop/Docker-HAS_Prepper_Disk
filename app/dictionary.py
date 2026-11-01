import asyncio
from collections import defaultdict
import io
import logging
import re
import shutil
import sqlite3
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from app.downloader import format_bytes

logger = logging.getLogger("prepper.dictionary")

PAREN_RE = re.compile(r"\([^)]*\)")
LATIN_LAT_RE = re.compile(r"\b[A-Z][a-z]+\s+[a-z]{3,}\b")  # ör. Felis domestica gibi bilimsel adları ele

# Kurulum (/setup) sayfasından indirilebilen Çift Yönlü Kelime Sözlükleri
DICTIONARY_PACKS: Dict[str, Dict[str, Any]] = {
    "eng_tur": {
        "id": "eng_tur",
        "name": "İngilizce ↔ Türkçe Sözlük",
        "desc": "İngilizce ➔ Türkçe ve Türkçe ➔ İngilizce çift yönlü kelimesi kelimesine sözlük.",
        "lang": "EN ↔ TR",
        "src_lang": "EN",
        "dst_lang": "TR",
        "headwords": 68000,
        "size": "~2.8 MB",
        "size_bytes": 2915280,
        "url": "https://download.freedict.org/dictionaries/eng-tur/0.3/freedict-eng-tur-0.3.src.tar.xz",
        "extra_urls": [
            "https://download.freedict.org/dictionaries/tur-eng/0.3/freedict-tur-eng-0.3.src.tar.xz",
        ],
    },
    "deu_tur": {
        "id": "deu_tur",
        "name": "Almanca ↔ Türkçe Sözlük",
        "desc": "Almanca ➔ Türkçe ve Türkçe ➔ Almanca çift yönlü kelime sözlüğü.",
        "lang": "DE ↔ TR",
        "src_lang": "DE",
        "dst_lang": "TR",
        "headwords": 54000,
        "size": "~535 KB",
        "size_bytes": 546588,
        "url": "https://download.freedict.org/dictionaries/deu-tur/0.2.2/freedict-deu-tur-0.2.2.src.tar.xz",
    },
    "fra_tur": {
        "id": "fra_tur",
        "name": "Fransızca ↔ Türkçe Sözlük",
        "desc": "Fransızca ➔ Türkçe ve Türkçe ➔ Fransızca çift yönlü kelime sözlüğü.",
        "lang": "FR ↔ TR",
        "src_lang": "FR",
        "dst_lang": "TR",
        "headwords": 22000,
        "size": "~475 KB",
        "size_bytes": 483240,
        "url": "https://download.freedict.org/dictionaries/fra-tur/2025.11.23/freedict-fra-tur-2025.11.23.src.tar.xz",
    },
    "spa_tur": {
        "id": "spa_tur",
        "name": "İspanyolca ↔ Türkçe Sözlük",
        "desc": "İspanyolca ➔ Türkçe ve Türkçe ➔ İspanyolca çift yönlü kelime sözlüğü.",
        "lang": "ES ↔ TR",
        "src_lang": "ES",
        "dst_lang": "TR",
        "headwords": 20000,
        "size": "~460 KB",
        "size_bytes": 470800,
        "url": "https://download.freedict.org/dictionaries/spa-tur/2024.10.10/freedict-spa-tur-2024.10.10.src.tar.xz",
    },
    "ita_tur": {
        "id": "ita_tur",
        "name": "İtalyanca ↔ Türkçe Sözlük",
        "desc": "İtalyanca ➔ Türkçe ve Türkçe ➔ İtalyanca çift yönlü kelime sözlüğü.",
        "lang": "IT ↔ TR",
        "src_lang": "IT",
        "dst_lang": "TR",
        "headwords": 34000,
        "size": "~760 KB",
        "size_bytes": 775532,
        "url": "https://download.freedict.org/dictionaries/ita-tur/2025.11.23/freedict-ita-tur-2025.11.23.src.tar.xz",
    },
    "ell_tur": {
        "id": "ell_tur",
        "name": "Yunanca ↔ Türkçe Sözlük",
        "desc": "Yunanca ➔ Türkçe ve Türkçe ➔ Yunanca çift yönlü kelime sözlüğü.",
        "lang": "EL ↔ TR",
        "src_lang": "EL",
        "dst_lang": "TR",
        "headwords": 19000,
        "size": "~275 KB",
        "size_bytes": 280132,
        "url": "https://download.freedict.org/dictionaries/ell-tur/2025.11.23/freedict-ell-tur-2025.11.23.src.tar.xz",
    },
    "kur_tur": {
        "id": "kur_tur",
        "name": "Kürtçe ↔ Türkçe Sözlük",
        "desc": "Kürtçe ➔ Türkçe ve Türkçe ➔ Kürtçe çift yönlü kelime sözlüğü.",
        "lang": "KU ↔ TR",
        "src_lang": "KU",
        "dst_lang": "TR",
        "headwords": 38000,
        "size": "~375 KB",
        "size_bytes": 383428,
        "url": "https://download.freedict.org/dictionaries/kur-tur/0.1.2/freedict-kur-tur-0.1.2.src.tar.xz",
    },
    "eng_ara": {
        "id": "eng_ara",
        "name": "İngilizce ↔ Arapça Sözlük",
        "desc": "İngilizce ➔ Arapça ve Arapça ➔ İngilizce çift yönlü kelime sözlüğü.",
        "lang": "EN ↔ AR",
        "src_lang": "EN",
        "dst_lang": "AR",
        "headwords": 95000,
        "size": "~865 KB",
        "size_bytes": 883268,
        "url": "https://download.freedict.org/dictionaries/eng-ara/0.6.3/freedict-eng-ara-0.6.3.src.tar.xz",
    },
    "eng_rus": {
        "id": "eng_rus",
        "name": "İngilizce ↔ Rusça Sözlük",
        "desc": "İngilizce ➔ Rusça ve Rusça ➔ İngilizce çift yönlü kelime sözlüğü.",
        "lang": "EN ↔ RU",
        "src_lang": "EN",
        "dst_lang": "RU",
        "headwords": 80000,
        "size": "~3.8 MB",
        "size_bytes": 3948540,
        "url": "https://download.freedict.org/dictionaries/eng-rus/2025.11.23/freedict-eng-rus-2025.11.23.src.tar.xz",
    },
    "eng_deu": {
        "id": "eng_deu",
        "name": "İngilizce ↔ Almanca Sözlük",
        "desc": "İngilizce ➔ Almanca ve Almanca ➔ İngilizce kapsamlı kelime sözlüğü.",
        "lang": "EN ↔ DE",
        "src_lang": "EN",
        "dst_lang": "DE",
        "headwords": 460000,
        "size": "~16.0 MB",
        "size_bytes": 16742600,
        "url": "https://download.freedict.org/dictionaries/eng-deu/1.9-fd1/freedict-eng-deu-1.9-fd1.src.tar.xz",
    },
    "eng_spa": {
        "id": "eng_spa",
        "name": "İngilizce ↔ İspanyolca Sözlük",
        "desc": "İngilizce ➔ İspanyolca ve İspanyolca ➔ İngilizce kelime sözlüğü.",
        "lang": "EN ↔ ES",
        "src_lang": "EN",
        "dst_lang": "ES",
        "headwords": 85000,
        "size": "~3.6 MB",
        "size_bytes": 3715012,
        "url": "https://download.freedict.org/dictionaries/eng-spa/2025.11.23/freedict-eng-spa-2025.11.23.src.tar.xz",
    },
}


class DictionaryManager:
    """
    Kurulum (/setup) sayfasından indirilebilen, hızlı ve sade
    kelimesi kelimesine (Kelime ➔ Karşılık) çevrimdışı sözlük motoru.
    """

    def __init__(self, dict_dir: Path, zim_dir: Path):
        self.dict_dir = dict_dir
        self.zim_dir = zim_dir
        self._fast_cache_dir = Path(tempfile.gettempdir()) / "prepper_dict_cache_v2"
        self._fast_cache_dir.mkdir(parents=True, exist_ok=True)
        self._stats_cache: Dict[str, Dict[str, Any]] = {}
        self._wiktionary_cache: Optional[tuple[float, List[Dict[str, Any]]]] = None
        self._download_states: Dict[str, Dict[str, Any]] = {}
        self._download_tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    def get_db_path(self, pack_id: str) -> Path:
        return self.dict_dir / f"{pack_id}.db"

    def _get_fast_db_path(self, pack_id: str) -> Path:
        fast_db = self._fast_cache_dir / f"{pack_id}.db"
        if fast_db.exists() and fast_db.stat().st_size > 4096:
            return fast_db
        src_db = self.get_db_path(pack_id)
        if src_db.exists() and src_db.stat().st_size > 4096:
            self._fast_cache_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src_db, fast_db)
            return fast_db
        return src_db

    def invalidate_cache(self, pack_id: Optional[str] = None) -> None:
        if pack_id:
            self._stats_cache.pop(pack_id, None)
        else:
            self._stats_cache.clear()
        self._wiktionary_cache = None

    def _get_cached_pack_stats(self, pack_id: str) -> Dict[str, Any]:
        if pack_id in self._stats_cache:
            return self._stats_cache[pack_id]
        db_file = self.get_db_path(pack_id)
        try:
            st_size = db_file.stat().st_size if db_file.exists() else 0
        except OSError:
            st_size = 0
        installed = st_size > 4096
        entry_count = DICTIONARY_PACKS.get(pack_id, {}).get("headwords", 0)
        if installed:
            fast_db = self._get_fast_db_path(pack_id)
            try:
                conn = sqlite3.connect(fast_db)
                try:
                    row = conn.execute("SELECT COUNT(*) FROM entries").fetchone()
                    if row:
                        entry_count = int(row[0])
                finally:
                    conn.close()
            except Exception:
                pass
        info = {
            "installed": installed,
            "disk_bytes": st_size if installed else 0,
            "entry_count": entry_count,
        }
        self._stats_cache[pack_id] = info
        return info

    def is_pack_installed(self, pack_id: str) -> bool:
        return bool(self._get_cached_pack_stats(pack_id)["installed"])

    def get_pack_entry_count(self, pack_id: str) -> int:
        return int(self._get_cached_pack_stats(pack_id)["entry_count"])

    def get_installed_wiktionary_zims(self) -> List[Dict[str, Any]]:
        now = time.monotonic()
        if self._wiktionary_cache and (now - self._wiktionary_cache[0] < 10.0):
            return self._wiktionary_cache[1]
        res = []
        if self.zim_dir.exists():
            for f in sorted(self.zim_dir.glob("wiktionary_*.zim")):
                if f.is_file():
                    book_id = f.stem
                    lang = "TR" if "_tr_" in f.name else ("EN" if "_en_" in f.name else "ÇOKLU")
                    res.append({
                        "book_id": book_id,
                        "filename": f.name,
                        "lang": lang,
                        "size_human": format_bytes(f.stat().st_size),
                        "href": f"/kiwix/{book_id}",
                    })
        self._wiktionary_cache = (now, res)
        return res

    def get_status(self) -> Dict[str, Any]:
        packs = []
        total_entries = 0
        installed_count = 0

        for pack_id, meta in DICTIONARY_PACKS.items():
            stats = self._get_cached_pack_stats(pack_id)
            inst = stats["installed"]
            disk_bytes = stats["disk_bytes"]
            entry_count = stats["entry_count"]
            if inst:
                installed_count += 1
                total_entries += entry_count

            dl_state = self._download_states.get(pack_id)
            is_dl = dl_state is not None and dl_state.get("stage") in ("downloading", "indexing")

            packs.append({
                **meta,
                "installed": inst,
                "downloading": is_dl,
                "download_state": dl_state,
                "entry_count": entry_count,
                "installed_bytes": disk_bytes,
                "installed_human": format_bytes(disk_bytes) if inst else meta["size"],
            })

        return {
            "installed_count": installed_count,
            "total_entries": total_entries,
            "packs": packs,
            "wiktionary_zims": self.get_installed_wiktionary_zims(),
        }

    async def download_packs(self, pack_ids: List[str]) -> Dict[str, Any]:
        started = []
        async with self._lock:
            self.dict_dir.mkdir(parents=True, exist_ok=True)
            for pid in pack_ids:
                if pid not in DICTIONARY_PACKS:
                    continue
                t = self._download_tasks.get(pid)
                if t is None or t.done():
                    meta = DICTIONARY_PACKS[pid]
                    self._download_states[pid] = {
                        "pack_id": pid,
                        "name": meta["name"],
                        "stage": "downloading",
                        "downloaded_bytes": 0,
                        "total_bytes": meta["size_bytes"],
                        "percent": 0.0,
                        "speed_human": "Başlatılıyor...",
                        "message": "Sözlük paketi indiriliyor...",
                    }
                    self._download_tasks[pid] = asyncio.create_task(self._download_and_index_pack(pid))
                    started.append(pid)
        return {"started": started, "status": self.get_status()}

    async def delete_pack(self, pack_id: str) -> Dict[str, Any]:
        async with self._lock:
            t = self._download_tasks.pop(pack_id, None)
            if t and not t.done():
                t.cancel()
            self._download_states.pop(pack_id, None)

            deleted = []
            for p in (
                self.get_db_path(pack_id),
                self.dict_dir / f"{pack_id}.db.tmp",
                self._fast_cache_dir / f"{pack_id}.db",
            ):
                if p.exists():
                    try:
                        p.unlink()
                        deleted.append(p.name)
                    except OSError as exc:
                        logger.error("Sözlük silinemedi (%s): %s", p, exc)
            self.invalidate_cache(pack_id)

        return {"deleted": deleted, "status": self.get_status()}

    async def _download_and_index_pack(self, pack_id: str) -> None:
        meta = DICTIONARY_PACKS[pack_id]
        state = self._download_states.get(pack_id) or {
            "pack_id": pack_id,
            "name": meta["name"],
            "stage": "downloading",
            "downloaded_bytes": 0,
            "total_bytes": meta["size_bytes"],
            "percent": 0.0,
            "speed_human": "—",
            "message": "Sözlük paketi indiriliyor...",
        }
        self._download_states[pack_id] = state

        try:
            urls = [meta["url"]] + meta.get("extra_urls", [])
            raw_archives: List[tuple[int, bytes]] = []

            async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
                for idx, url in enumerate(urls):
                    async with client.stream("GET", url) as resp:
                        resp.raise_for_status()
                        content_len = int(resp.headers.get("Content-Length", 0)) or meta["size_bytes"]
                        if idx == 0:
                            state["total_bytes"] = content_len

                        buf = io.BytesIO()
                        downloaded = 0
                        last_tick = time.monotonic()
                        bytes_tick = 0
                        smoothed_speed = 0.0

                        async for chunk in resp.aiter_bytes(chunk_size=128 * 1024):
                            buf.write(chunk)
                            downloaded += len(chunk)
                            bytes_tick += len(chunk)
                            now = time.monotonic()
                            if now - last_tick >= 0.25:
                                spd = bytes_tick / (now - last_tick)
                                smoothed_speed = spd if smoothed_speed == 0 else (0.7 * smoothed_speed + 0.3 * spd)
                                last_tick = now
                                bytes_tick = 0
                                pct = round((downloaded / content_len) * 85, 1) if content_len > 0 else 50.0
                                state.update({
                                    "downloaded_bytes": downloaded,
                                    "percent": min(pct, 85.0),
                                    "speed_human": f"{format_bytes(smoothed_speed)}/s",
                                    "message": f"{format_bytes(downloaded)} / {format_bytes(content_len)}",
                                })
                        raw_archives.append((idx, buf.getvalue()))

            state["stage"] = "indexing"
            state["percent"] = 92.0
            state["message"] = "Çift yönlü kelime dizini oluşturuluyor..."

            count = await asyncio.to_thread(self._build_clean_word_db, pack_id, meta, raw_archives)
            state["stage"] = "completed"
            state["percent"] = 100.0
            state["message"] = f"Kuruldu ({count} kelime)"

        except asyncio.CancelledError:
            state["stage"] = "cancelled"
            state["message"] = "İptal edildi."
            raise
        except Exception as exc:
            logger.exception("Sözlük indirme/kurma hatası (%s): %s", pack_id, exc)
            state["stage"] = "error"
            state["message"] = f"Hata: {exc}"
        finally:
            await asyncio.sleep(1.2)
            if self._download_states.get(pack_id, {}).get("stage") in ("completed", "cancelled"):
                self._download_states.pop(pack_id, None)

    def _init_sqlite_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                headword TEXT NOT NULL,
                headword_lower TEXT NOT NULL,
                pron TEXT,
                pos TEXT,
                definition TEXT NOT NULL,
                def_lower TEXT NOT NULL,
                lang_pair TEXT,
                category TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_hw_lower ON entries(headword_lower)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lang_pair ON entries(lang_pair)")

    def _extract_clean_terms(self, joined_text: str) -> List[str]:
        """
        Uzun ansiklopedik paragrafları ve deyim örneklerini atarak yalnızca
        kelimenin doğrudan, yalın sözlük karşılıklarını (1-5 kelime) çıkarır.
        """
        no_paren = PAREN_RE.sub("", joined_text)
        # İlk noktadan ('.') sonraki bileşik deyim ve örnek cümleleri kes
        main_part = no_paren.split(".")[0]
        clean_terms: List[str] = []
        for piece in re.split(r"[;,]", main_part):
            t = " ".join(piece.strip(" .:-—\"'").split())
            if not t or len(t) > 38 or ":" in t:
                continue
            if LATIN_LAT_RE.search(t):
                continue
            if t not in clean_terms:
                clean_terms.append(t)
        return clean_terms

    def _build_clean_word_db(
        self,
        pack_id: str,
        meta: Dict[str, Any],
        raw_archives: List[tuple[int, bytes]],
    ) -> int:
        tmp_db = Path(tempfile.gettempdir()) / f"prepper_dict_{pack_id}.db"
        final_db = self.get_db_path(pack_id)
        if tmp_db.exists():
            tmp_db.unlink()

        src_lang = meta.get("src_lang", "EN")
        dst_lang = meta.get("dst_lang", "TR")
        fwd_dir = f"{src_lang} ➔ {dst_lang}"
        rev_dir = f"{dst_lang} ➔ {src_lang}"

        ns = "{http://www.tei-c.org/ns/1.0}"

        fwd_map: Dict[str, Dict[str, Any]] = {}
        rev_map: Dict[str, Dict[str, Any]] = {}
        word_weight: Dict[str, int] = defaultdict(int)

        for archive_idx, raw_bytes in raw_archives:
            is_reverse_archive = archive_idx > 0
            with tarfile.open(fileobj=io.BytesIO(raw_bytes), mode="r:xz") as tf:
                for member in tf.getmembers():
                    if not member.name.endswith(".tei"):
                        continue
                    f = tf.extractfile(member)
                    if not f:
                        continue
                    for event, elem in ET.iterparse(f, events=("end",)):
                        if elem.tag == f"{ns}entry":
                            orth = (elem.findtext(f".//{ns}orth") or "").strip()
                            if orth and len(orth) <= 40:
                                pron = (elem.findtext(f".//{ns}pron") or "").strip()
                                pos = (elem.findtext(f".//{ns}pos") or "").strip()
                                quotes = [q.text.strip() for q in elem.findall(f".//{ns}quote") if q.text and q.text.strip()]
                                defs = [d.text.strip() for d in elem.findall(f".//{ns}def") if d.text and d.text.strip()]
                                joined = " ; ".join(quotes if quotes else defs)
                                is_abbrev = joined.strip().startswith("(kıs.)")
                                terms = self._extract_clean_terms(joined)

                                if terms:
                                    if is_reverse_archive:
                                        # Doğrudan tur-eng gibi ters sözlük arşivi
                                        low = orth.lower()
                                        rec = rev_map.setdefault(low, {"display": orth, "pri1": [], "pri2": []})
                                        for t in terms[:5]:
                                            if t not in rec["pri1"]:
                                                rec["pri1"].append(t)
                                    else:
                                        rec = fwd_map.setdefault(
                                            orth,
                                            {"pron": pron, "pos": pos, "primary": [], "secondary": []},
                                        )
                                        if not rec["pron"] and pron:
                                            rec["pron"] = pron
                                        if not rec["pos"] and pos:
                                            rec["pos"] = pos

                                        word_weight[orth] += len(joined)
                                        target_bucket = rec["secondary"] if is_abbrev else rec["primary"]
                                        # Yalnızca yeni girişin ilk anlamı mevcut ilk anlamdan daha kısaysa öne al (ör. 'kitap' < 'deftere geçirmek')
                                        if not is_abbrev and target_bucket and len(terms[0]) < len(target_bucket[0]):
                                            for t in reversed(terms[:5]):
                                                if t not in target_bucket:
                                                    target_bucket.insert(0, t)
                                        else:
                                            for t in terms[:5]:
                                                if t not in target_bucket:
                                                    target_bucket.append(t)

                                        # Ters yön (ör. TR ➔ EN) kelime eşleştirmesi üret
                                        if not is_abbrev and len(orth.split()) <= 2:
                                            for t_idx, t in enumerate(terms[:4]):
                                                t_low = t.lower()
                                                if len(t.split()) <= 3 and len(t_low) >= 2:
                                                    r_rec = rev_map.setdefault(
                                                        t_low,
                                                        {"display": t, "pri1": [], "pri2": []},
                                                    )
                                                    bucket = r_rec["pri1"] if t_idx == 0 else r_rec["pri2"]
                                                    if orth not in r_rec["pri1"] and orth not in r_rec["pri2"]:
                                                        bucket.append(orth)
                            elem.clear()

        rows = []
        # 1. İleri yön (ör. EN ➔ TR) satırları
        for orth, data in fwd_map.items():
            combined = data["primary"] + [x for x in data["secondary"] if x not in data["primary"]]
            if not combined:
                continue
            def_str = ", ".join(combined[:6])
            rows.append((
                orth,
                orth.lower(),
                data["pron"],
                data["pos"],
                def_str,
                def_str.lower(),
                fwd_dir,
                meta["name"],
            ))

        # 2. Ters yön (ör. TR ➔ EN) satırları (en yaygın/temel kelimeler en önde)
        for t_low, r_data in rev_map.items():
            pri1 = sorted(r_data["pri1"], key=lambda w: (-word_weight.get(w, 0), len(w), w))
            pri2 = sorted(r_data["pri2"], key=lambda w: (-word_weight.get(w, 0), len(w), w))
            combined = pri1 + [w for w in pri2 if w not in pri1]
            if not combined:
                continue
            def_str = ", ".join(combined[:6])
            hw = r_data["display"]
            rows.append((
                hw,
                t_low,
                "",
                "",
                def_str,
                def_str.lower(),
                rev_dir,
                meta["name"],
            ))

        rows.sort(key=lambda r: (r[1], r[6]))

        conn = sqlite3.connect(tmp_db)
        try:
            self._init_sqlite_schema(conn)
            conn.executemany(
                """
                INSERT INTO entries (headword, headword_lower, pron, pos, definition, def_lower, lang_pair, category)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

        self.dict_dir.mkdir(parents=True, exist_ok=True)
        self._fast_cache_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tmp_db, self._fast_cache_dir / f"{pack_id}.db")
        shutil.copyfile(tmp_db, final_db)
        tmp_db.unlink(missing_ok=True)
        self.invalidate_cache(pack_id)
        return len(rows)

    def search_entries(
        self,
        query: str = "",
        pack_id: str = "all",
        direction: str = "all",
        limit: int = 80,
    ) -> Dict[str, Any]:
        t0 = time.monotonic()
        q = query.strip()
        q_low = q.replace("İ", "i").replace("I", "ı").lower().replace("\u0307", "")

        target_packs = []
        if pack_id and pack_id != "all":
            if self.is_pack_installed(pack_id):
                target_packs.append(pack_id)
        else:
            for pid in DICTIONARY_PACKS:
                if self.is_pack_installed(pid):
                    target_packs.append(pid)

        results = []
        for pid in target_packs:
            db_file = self._get_fast_db_path(pid)
            meta = DICTIONARY_PACKS.get(pid, {})
            try:
                conn = sqlite3.connect(db_file)
                try:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()

                    dir_clause = ""
                    dir_params: List[Any] = []
                    if direction == "to_tr":
                        dir_clause = " AND lang_pair LIKE '%➔ TR'"
                    elif direction == "from_tr":
                        dir_clause = " AND lang_pair LIKE 'TR ➔%'"

                    if not q_low:
                        sql = f"SELECT *, 3 AS rank_score FROM entries WHERE LENGTH(headword) BETWEEN 3 AND 10 {dir_clause} LIMIT ?"
                        cur.execute(sql, [min(limit, 50)])
                        rows = cur.fetchall()
                    elif len(q_low) == 1:
                        # Tek harf seçildiyse o harfle başlayan kelimeler
                        sql = f"""
                        SELECT *, 1 AS rank_score
                        FROM entries
                        WHERE headword_lower LIKE ? {dir_clause}
                        ORDER BY LENGTH(headword) ASC, headword_lower ASC
                        LIMIT ?
                        """
                        cur.execute(sql, [f"{q_low}%", limit])
                        rows = cur.fetchall()
                    else:
                        # Yalnızca madde başı (kelime) üzerinden tam veya önek eşleşmesi!
                        sql = f"""
                        SELECT *,
                          CASE
                            WHEN headword_lower = ? THEN 1
                            WHEN headword_lower LIKE ? THEN 2
                            ELSE 3
                          END AS rank_score
                        FROM entries
                        WHERE headword_lower LIKE ? {dir_clause}
                        ORDER BY rank_score ASC, LENGTH(headword) ASC, headword_lower ASC
                        LIMIT ?
                        """
                        cur.execute(
                            sql,
                            [q_low, f"{q_low}%", f"{q_low}%", limit],
                        )
                        rows = cur.fetchall()

                        # Önek ile sonuç çıkmadıysa kelime içi eşleşmeye bak
                        if not rows:
                            sql_sub = f"""
                            SELECT *, 4 AS rank_score
                            FROM entries
                            WHERE (headword_lower LIKE ? OR def_lower LIKE ?) {dir_clause}
                            ORDER BY LENGTH(headword) ASC
                            LIMIT ?
                            """
                            cur.execute(sql_sub, [f"%{q_low}%", f"%{q_low}%", limit])
                            rows = cur.fetchall()

                    for r in rows:
                        results.append({
                            "pack_id": pid,
                            "pack_name": meta.get("name", pid),
                            "headword": r["headword"],
                            "pron": r["pron"] or "",
                            "pos": r["pos"] or "",
                            "definition": r["definition"],
                            "lang_pair": r["lang_pair"] or meta.get("lang", ""),
                            "rank": r["rank_score"] if "rank_score" in r.keys() else 5,
                        })
                finally:
                    conn.close()
            except Exception as exc:
                logger.error("Sözlük arama hatası (%s): %s", pid, exc)

        if q_low:
            results.sort(key=lambda x: (x["rank"], len(x["headword"]), x["headword"].lower()))
        results = results[:limit]

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return {
            "query": q,
            "count": len(results),
            "elapsed_ms": elapsed_ms,
            "items": results,
            "wiktionary_zims": self.get_installed_wiktionary_zims(),
        }
