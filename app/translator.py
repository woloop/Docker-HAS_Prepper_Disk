import asyncio
import logging
import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Any
import httpx

from app.downloader import format_bytes

logger = logging.getLogger("prepper.translator")

# Argos Translate Resmi Çevrimdışı Sinirsel Çeviri Modelleri (CTranslate2 + SentencePiece)
LANGUAGE_PACKS: Dict[str, Dict[str, Any]] = {
    "en_tr": {
        "id": "en_tr", "from_code": "en", "to_code": "tr", "lang_code": "tr",
        "name": "İngilizce ➔ Türkçe (EN ➔ TR)",
        "url": "https://argos-net.com/v1/translate-en_tr-1_5.argosmodel",
        "size": "~119 MB", "size_bytes": 124742526,
    },
    "tr_en": {
        "id": "tr_en", "from_code": "tr", "to_code": "en", "lang_code": "tr",
        "name": "Türkçe ➔ İngilizce (TR ➔ EN)",
        "url": "https://argos-net.com/v1/translate-tr_en-1_5.argosmodel",
        "size": "~119 MB", "size_bytes": 124700000,
    },
    "en_de": {
        "id": "en_de", "from_code": "en", "to_code": "de", "lang_code": "de",
        "name": "İngilizce ➔ Almanca (EN ➔ DE)",
        "url": "https://argos-net.com/v1/translate-en_de-1_3.argosmodel",
        "size": "~98 MB", "size_bytes": 102000000,
    },
    "de_en": {
        "id": "de_en", "from_code": "de", "to_code": "en", "lang_code": "de",
        "name": "Almanca ➔ İngilizce (DE ➔ EN)",
        "url": "https://argos-net.com/v1/translate-de_en-1_3.argosmodel",
        "size": "~98 MB", "size_bytes": 102000000,
    },
    "en_fr": {
        "id": "en_fr", "from_code": "en", "to_code": "fr", "lang_code": "fr",
        "name": "İngilizce ➔ Fransızca (EN ➔ FR)",
        "url": "https://argos-net.com/v1/translate-en_fr-1_9.argosmodel",
        "size": "~105 MB", "size_bytes": 110000000,
    },
    "fr_en": {
        "id": "fr_en", "from_code": "fr", "to_code": "en", "lang_code": "fr",
        "name": "Fransızca ➔ İngilizce (FR ➔ EN)",
        "url": "https://argos-net.com/v1/translate-fr_en-1_9.argosmodel",
        "size": "~105 MB", "size_bytes": 110000000,
    },
    "en_es": {
        "id": "en_es", "from_code": "en", "to_code": "es", "lang_code": "es",
        "name": "İngilizce ➔ İspanyolca (EN ➔ ES)",
        "url": "https://argos-net.com/v1/translate-en_es-1_0.argosmodel",
        "size": "~102 MB", "size_bytes": 107000000,
    },
    "es_en": {
        "id": "es_en", "from_code": "es", "to_code": "en", "lang_code": "es",
        "name": "İspanyolca ➔ İngilizce (ES ➔ EN)",
        "url": "https://argos-net.com/v1/translate-es_en-1_9.argosmodel",
        "size": "~102 MB", "size_bytes": 107000000,
    },
    "en_ru": {
        "id": "en_ru", "from_code": "en", "to_code": "ru", "lang_code": "ru",
        "name": "İngilizce ➔ Rusça (EN ➔ RU)",
        "url": "https://argos-net.com/v1/translate-en_ru-1_9.argosmodel",
        "size": "~108 MB", "size_bytes": 113000000,
    },
    "ru_en": {
        "id": "ru_en", "from_code": "ru", "to_code": "en", "lang_code": "ru",
        "name": "Rusça ➔ İngilizce (RU ➔ EN)",
        "url": "https://argos-net.com/v1/translate-ru_en-1_9.argosmodel",
        "size": "~108 MB", "size_bytes": 113000000,
    },
    "en_ar": {
        "id": "en_ar", "from_code": "en", "to_code": "ar", "lang_code": "ar",
        "name": "İngilizce ➔ Arapça (EN ➔ AR)",
        "url": "https://argos-net.com/v1/translate-en_ar-1_0.argosmodel",
        "size": "~95 MB", "size_bytes": 100000000,
    },
    "ar_en": {
        "id": "ar_en", "from_code": "ar", "to_code": "en", "lang_code": "ar",
        "name": "Arapça ➔ İngilizce (AR ➔ EN)",
        "url": "https://argos-net.com/v1/translate-ar_en-1_0.argosmodel",
        "size": "~95 MB", "size_bytes": 100000000,
    },
    "en_it": {
        "id": "en_it", "from_code": "en", "to_code": "it", "lang_code": "it",
        "name": "İngilizce ➔ İtalyanca (EN ➔ IT)",
        "url": "https://argos-net.com/v1/translate-en_it-1_0.argosmodel",
        "size": "~95 MB", "size_bytes": 100000000,
    },
    "it_en": {
        "id": "it_en", "from_code": "it", "to_code": "en", "lang_code": "it",
        "name": "İtalyanca ➔ İngilizce (IT ➔ EN)",
        "url": "https://argos-net.com/v1/translate-it_en-1_0.argosmodel",
        "size": "~95 MB", "size_bytes": 100000000,
    },
    "en_el": {
        "id": "en_el", "from_code": "en", "to_code": "el", "lang_code": "el",
        "name": "İngilizce ➔ Yunanca (EN ➔ EL)",
        "url": "https://argos-net.com/v1/translate-en_el-1_9.argosmodel",
        "size": "~105 MB", "size_bytes": 110000000,
    },
    "el_en": {
        "id": "el_en", "from_code": "el", "to_code": "en", "lang_code": "el",
        "name": "Yunanca ➔ İngilizce (EL ➔ EN)",
        "url": "https://argos-net.com/v1/translate-el_en-1_9.argosmodel",
        "size": "~105 MB", "size_bytes": 110000000,
    },
    "en_fa": {
        "id": "en_fa", "from_code": "en", "to_code": "fa", "lang_code": "fa",
        "name": "İngilizce ➔ Farsça (EN ➔ FA)",
        "url": "https://argos-net.com/v1/translate-en_fa-1_5.argosmodel",
        "size": "~100 MB", "size_bytes": 105000000,
    },
    "fa_en": {
        "id": "fa_en", "from_code": "fa", "to_code": "en", "lang_code": "fa",
        "name": "Farsça ➔ İngilizce (FA ➔ EN)",
        "url": "https://argos-net.com/v1/translate-fa_en-1_5.argosmodel",
        "size": "~100 MB", "size_bytes": 105000000,
    },
    "en_az": {
        "id": "en_az", "from_code": "en", "to_code": "az", "lang_code": "az",
        "name": "İngilizce ➔ Azerbaycan Türkçesi (EN ➔ AZ)",
        "url": "https://argos-net.com/v1/translate-en_az-1_5.argosmodel",
        "size": "~100 MB", "size_bytes": 105000000,
    },
    "az_en": {
        "id": "az_en", "from_code": "az", "to_code": "en", "lang_code": "az",
        "name": "Azerbaycan Türkçesi ➔ İngilizce (AZ ➔ EN)",
        "url": "https://argos-net.com/v1/translate-az_en-1_5.argosmodel",
        "size": "~100 MB", "size_bytes": 105000000,
    },
    "en_uk": {
        "id": "en_uk", "from_code": "en", "to_code": "uk", "lang_code": "uk",
        "name": "İngilizce ➔ Ukraynaca (EN ➔ UK)",
        "url": "https://argos-net.com/v1/translate-en_uk-1_4.argosmodel",
        "size": "~105 MB", "size_bytes": 110000000,
    },
    "uk_en": {
        "id": "uk_en", "from_code": "uk", "to_code": "en", "lang_code": "uk",
        "name": "Ukraynaca ➔ İngilizce (UK ➔ EN)",
        "url": "https://argos-net.com/v1/translate-uk_en-1_9.argosmodel",
        "size": "~105 MB", "size_bytes": 110000000,
    },
    "en_zh": {
        "id": "en_zh", "from_code": "en", "to_code": "zh", "lang_code": "zh",
        "name": "İngilizce ➔ Çince (EN ➔ ZH)",
        "url": "https://argos-net.com/v1/translate-en_zh-1_9.argosmodel",
        "size": "~110 MB", "size_bytes": 115000000,
    },
    "zh_en": {
        "id": "zh_en", "from_code": "zh", "to_code": "en", "lang_code": "zh",
        "name": "Çince ➔ İngilizce (ZH ➔ EN)",
        "url": "https://argos-net.com/v1/translate-zh_en-1_9.argosmodel",
        "size": "~110 MB", "size_bytes": 115000000,
    },
    "en_pt": {
        "id": "en_pt", "from_code": "en", "to_code": "pt", "lang_code": "pt",
        "name": "İngilizce ➔ Portekizce (EN ➔ PT)",
        "url": "https://argos-net.com/v1/translate-en_pt-1_9.argosmodel",
        "size": "~105 MB", "size_bytes": 110000000,
    },
    "pt_en": {
        "id": "pt_en", "from_code": "pt", "to_code": "en", "lang_code": "pt",
        "name": "Portekizce ➔ İngilizce (PT ➔ EN)",
        "url": "https://argos-net.com/v1/translate-pt_en-1_9.argosmodel",
        "size": "~105 MB", "size_bytes": 110000000,
    },
    "en_nl": {
        "id": "en_nl", "from_code": "en", "to_code": "nl", "lang_code": "nl",
        "name": "İngilizce ➔ Felemenkçe (EN ➔ NL)",
        "url": "https://argos-net.com/v1/translate-en_nl-1_8.argosmodel",
        "size": "~102 MB", "size_bytes": 107000000,
    },
    "nl_en": {
        "id": "nl_en", "from_code": "nl", "to_code": "en", "lang_code": "nl",
        "name": "Felemenkçe ➔ İngilizce (NL ➔ EN)",
        "url": "https://argos-net.com/v1/translate-nl_en-1_8.argosmodel",
        "size": "~102 MB", "size_bytes": 107000000,
    },
}

LANGUAGE_BUNDLES: List[Dict[str, Any]] = [
    {"code": "tr", "name": "Türkçe", "native": "Türkçe", "packs": ["en_tr", "tr_en"], "size": "~238 MB", "size_bytes": 249442526, "desc": "İngilizce ↔ Türkçe çift yönlü çevrimdışı sinirsel çeviri paketi."},
    {"code": "de", "name": "Almanca", "native": "Deutsch", "packs": ["en_de", "de_en"], "size": "~196 MB", "size_bytes": 204000000, "desc": "İngilizce ↔ Almanca (ve Türkçe ↔ Almanca köprü) çeviri paketi."},
    {"code": "fr", "name": "Fransızca", "native": "Français", "packs": ["en_fr", "fr_en"], "size": "~210 MB", "size_bytes": 220000000, "desc": "İngilizce ↔ Fransızca (ve Türkçe ↔ Fransızca köprü) çeviri paketi."},
    {"code": "es", "name": "İspanyolca", "native": "Español", "packs": ["en_es", "es_en"], "size": "~204 MB", "size_bytes": 214000000, "desc": "İngilizce ↔ İspanyolca (ve Türkçe ↔ İspanyolca köprü) çeviri paketi."},
    {"code": "ru", "name": "Rusça", "native": "Русский", "packs": ["en_ru", "ru_en"], "size": "~216 MB", "size_bytes": 226000000, "desc": "İngilizce ↔ Rusça (ve Türkçe ↔ Rusça köprü) çeviri paketi."},
    {"code": "ar", "name": "Arapça", "native": "العربية", "packs": ["en_ar", "ar_en"], "size": "~190 MB", "size_bytes": 200000000, "desc": "İngilizce ↔ Arapça (ve Türkçe ↔ Arapça köprü) çeviri paketi."},
    {"code": "it", "name": "İtalyanca", "native": "Italiano", "packs": ["en_it", "it_en"], "size": "~190 MB", "size_bytes": 200000000, "desc": "İngilizce ↔ İtalyanca (ve Türkçe ↔ İtalyanca köprü) çeviri paketi."},
    {"code": "el", "name": "Yunanca", "native": "Ελληνικά", "packs": ["en_el", "el_en"], "size": "~210 MB", "size_bytes": 220000000, "desc": "İngilizce ↔ Yunanca (ve Türkçe ↔ Yunanca köprü) çeviri paketi."},
    {"code": "fa", "name": "Farsça", "native": "فارسی", "packs": ["en_fa", "fa_en"], "size": "~200 MB", "size_bytes": 210000000, "desc": "İngilizce ↔ Farsça (ve Türkçe ↔ Farsça köprü) çeviri paketi."},
    {"code": "az", "name": "Azerbaycan Türkçesi", "native": "Azərbaycanca", "packs": ["en_az", "az_en"], "size": "~200 MB", "size_bytes": 210000000, "desc": "İngilizce ↔ Azerbaycan Türkçesi çeviri paketi."},
    {"code": "uk", "name": "Ukraynaca", "native": "Українська", "packs": ["en_uk", "uk_en"], "size": "~210 MB", "size_bytes": 220000000, "desc": "İngilizce ↔ Ukraynaca çeviri paketi."},
    {"code": "zh", "name": "Çince", "native": "中文", "packs": ["en_zh", "zh_en"], "size": "~220 MB", "size_bytes": 230000000, "desc": "İngilizce ↔ Çince çeviri paketi."},
    {"code": "pt", "name": "Portekizce", "native": "Português", "packs": ["en_pt", "pt_en"], "size": "~210 MB", "size_bytes": 220000000, "desc": "İngilizce ↔ Portekizce çeviri paketi."},
    {"code": "nl", "name": "Felemenkçe", "native": "Nederlands", "packs": ["en_nl", "nl_en"], "size": "~204 MB", "size_bytes": 214000000, "desc": "İngilizce ↔ Felemenkçe çeviri paketi."},
]

LANG_NAMES: Dict[str, str] = {
    "en": "İngilizce (EN)",
    **{b["code"]: f"{b['name']} ({b['code'].upper()})" for b in LANGUAGE_BUNDLES}
}

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


class LocalTranslator:
    """
    CTranslate2 + SentencePiece kullanarak %100 çevrimdışı (internet olmadan)
    çok dilli sinirsel makine çevirisi (ve EN üzerinden köprü çevirisi) yapan yerel motor.
    """

    def __init__(self, models_dir: Path):
        self.models_dir = models_dir
        self._loaded_models: Dict[str, Dict[str, Any]] = {}
        self._download_states: Dict[str, Dict[str, Any]] = {}
        self._download_tasks: Dict[str, asyncio.Task] = {}
        self._pack_info_cache: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def _inspect_pack_on_disk(self, pack_id: str) -> Dict[str, Any]:
        pack_dir = self.models_dir / pack_id
        if not pack_dir.exists():
            return {"installed": False, "disk_bytes": 0, "model_bin": None, "sp_model": None}
        model_bin = None
        sp_model = None
        total_size = 0
        for f in pack_dir.rglob("*"):
            if f.is_file():
                try:
                    total_size += f.stat().st_size
                except OSError:
                    pass
                if f.name == "model.bin" and model_bin is None:
                    model_bin = str(f)
                elif f.suffix == ".model" and sp_model is None:
                    sp_model = str(f)
        installed = bool(model_bin and sp_model)
        return {
            "installed": installed,
            "disk_bytes": total_size if installed else 0,
            "model_bin": model_bin,
            "sp_model": sp_model,
        }

    def _get_cached_pack_info(self, pack_id: str) -> Dict[str, Any]:
        if pack_id not in self._pack_info_cache:
            self._pack_info_cache[pack_id] = self._inspect_pack_on_disk(pack_id)
        return self._pack_info_cache[pack_id]

    def invalidate_cache(self, pack_id: Optional[str] = None) -> None:
        if pack_id:
            self._pack_info_cache.pop(pack_id, None)
        else:
            self._pack_info_cache.clear()

    def is_pack_installed(self, pack_id: str) -> bool:
        return bool(self._get_cached_pack_info(pack_id)["installed"])

    def get_pack_disk_size(self, pack_id: str) -> int:
        return int(self._get_cached_pack_info(pack_id)["disk_bytes"])

    def get_status(self) -> Dict[str, Any]:
        packs = []
        for pack_id, meta in LANGUAGE_PACKS.items():
            installed = self.is_pack_installed(pack_id)
            dl_state = self._download_states.get(pack_id)
            packs.append({
                **meta,
                "installed": installed,
                "downloading": dl_state is not None and dl_state.get("stage") in ("downloading", "extracting"),
                "download_state": dl_state,
            })

        languages = []
        installed_lang_codes = ["en"]
        for bundle in LANGUAGE_BUNDLES:
            p_ids = bundle["packs"]
            inst_flags = [self.is_pack_installed(pid) for pid in p_ids]
            all_inst = all(inst_flags)
            any_inst = any(inst_flags)
            if all_inst:
                installed_lang_codes.append(bundle["code"])

            dl_states = [
                self._download_states[pid]
                for pid in p_ids
                if pid in self._download_states and self._download_states[pid].get("stage") in ("downloading", "extracting")
            ]
            is_downloading = len(dl_states) > 0
            combined_pct = 0.0
            speed_str = "—"
            msg_str = ""
            if is_downloading:
                total_b = sum(s.get("total_bytes", 1) for s in dl_states) or 1
                dl_b = sum(s.get("downloaded_bytes", 0) for s in dl_states)
                combined_pct = round((dl_b / total_b) * 100, 1)
                speed_str = dl_states[0].get("speed_human", "—")
                msg_str = f"{format_bytes(dl_b)} / {format_bytes(total_b)}"

            disk_bytes = sum(self.get_pack_disk_size(pid) for pid in p_ids) if any_inst else 0

            languages.append({
                **bundle,
                "installed": all_inst,
                "partial": any_inst and not all_inst,
                "downloading": is_downloading,
                "percent": min(combined_pct, 100.0),
                "speed_human": speed_str,
                "message": msg_str,
                "installed_bytes": disk_bytes,
                "installed_human": format_bytes(disk_bytes) if disk_bytes > 0 else bundle["size"],
            })

        return {
            "ready": all(self.is_pack_installed(k) for k in ("en_tr", "tr_en")),
            "any_installed": any(self.is_pack_installed(k) for k in LANGUAGE_PACKS),
            "installed_languages": installed_lang_codes,
            "lang_names": LANG_NAMES,
            "languages": languages,
            "packs": packs,
        }

    async def download_packs(
        self,
        pack_ids: Optional[List[str]] = None,
        lang_codes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Dil paketlerini (pack_ids veya lang_codes ile) paralel olarak indirir ve kurar.
        """
        targets: List[str] = []
        if lang_codes:
            for lc in lang_codes:
                for b in LANGUAGE_BUNDLES:
                    if b["code"] == lc:
                        targets.extend(b["packs"])
        if pack_ids:
            targets.extend(pack_ids)
        if not targets:
            targets = ["en_tr", "tr_en"]

        started = []
        async with self._lock:
            self.models_dir.mkdir(parents=True, exist_ok=True)
            for pid in dict.fromkeys(targets):
                if pid not in LANGUAGE_PACKS:
                    continue
                if self.is_pack_installed(pid):
                    continue
                t = self._download_tasks.get(pid)
                if t is None or t.done():
                    meta = LANGUAGE_PACKS[pid]
                    self._download_states[pid] = {
                        "pack_id": pid,
                        "name": meta["name"],
                        "stage": "downloading",
                        "downloaded_bytes": 0,
                        "total_bytes": meta["size_bytes"],
                        "percent": 0.0,
                        "speed_human": "Başlatılıyor...",
                        "message": "Dil modeli indiriliyor...",
                    }
                    self._download_tasks[pid] = asyncio.create_task(self._download_single_pack(pid))
                    started.append(pid)
        return {"started": started, "status": self.get_status()}

    async def delete_language(self, lang_or_pack: str) -> Dict[str, Any]:
        """
        Belirtilen dil koduna (ör. 'de') veya paket kimliğine (ör. 'en_de') ait modelleri siler.
        """
        target_packs = []
        for b in LANGUAGE_BUNDLES:
            if b["code"] == lang_or_pack:
                target_packs.extend(b["packs"])
        if not target_packs and lang_or_pack in LANGUAGE_PACKS:
            target_packs.append(lang_or_pack)

        deleted = []
        async with self._lock:
            for pid in target_packs:
                t = self._download_tasks.pop(pid, None)
                if t and not t.done():
                    t.cancel()
                self._download_states.pop(pid, None)
                self._loaded_models.pop(pid, None)
                self.invalidate_cache(pid)

                for p in (
                    self.models_dir / pid,
                    self.models_dir / f"{pid}.tmp",
                    self.models_dir / f"{pid}.argosmodel",
                    self.models_dir / f"{pid}.argosmodel.part",
                ):
                    if p.exists():
                        try:
                            if p.is_dir():
                                shutil.rmtree(p)
                            else:
                                p.unlink()
                            deleted.append(p.name)
                        except OSError as exc:
                            logger.error("Model silinemedi (%s): %s", p, exc)

        return {"deleted": deleted, "status": self.get_status()}

    async def _download_single_pack(self, pack_id: str) -> None:
        meta = LANGUAGE_PACKS[pack_id]
        url = meta["url"]
        part_file = self.models_dir / f"{pack_id}.argosmodel.part"
        archive_file = self.models_dir / f"{pack_id}.argosmodel"
        dest_dir = self.models_dir / pack_id

        state = {
            "pack_id": pack_id,
            "name": meta["name"],
            "stage": "downloading",
            "downloaded_bytes": 0,
            "total_bytes": meta["size_bytes"],
            "percent": 0.0,
            "speed_human": "—",
            "message": "Dil modeli indiriliyor...",
        }
        self._download_states[pack_id] = state

        try:
            resume_bytes = part_file.stat().st_size if part_file.exists() else 0
            headers = {"Range": f"bytes={resume_bytes}-"} if resume_bytes > 0 else {}

            async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
                async with client.stream("GET", url, headers=headers) as resp:
                    if resp.status_code == 416:
                        part_file.unlink(missing_ok=True)
                        resume_bytes = 0
                        headers = {}
                    if resp.status_code not in (200, 206):
                        resp.raise_for_status()

                    is_resumed = resp.status_code == 206
                    if not is_resumed:
                        resume_bytes = 0

                    content_len = int(resp.headers.get("Content-Length", 0))
                    total = (resume_bytes + content_len) if content_len > 0 else meta["size_bytes"]
                    state["total_bytes"] = total

                    downloaded = resume_bytes
                    last_tick = time.monotonic()
                    bytes_tick = 0
                    smoothed_speed = 0.0

                    with open(part_file, "ab" if is_resumed else "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=256 * 1024):
                            f.write(chunk)
                            downloaded += len(chunk)
                            bytes_tick += len(chunk)
                            now = time.monotonic()
                            if now - last_tick >= 0.35:
                                spd = bytes_tick / (now - last_tick)
                                smoothed_speed = spd if smoothed_speed == 0 else (0.7 * smoothed_speed + 0.3 * spd)
                                last_tick = now
                                bytes_tick = 0
                                pct = round((downloaded / total) * 100, 1) if total > 0 else 0.0
                                state.update({
                                    "downloaded_bytes": downloaded,
                                    "percent": min(pct, 100.0),
                                    "speed_human": f"{format_bytes(smoothed_speed)}/s",
                                    "message": f"{format_bytes(downloaded)} / {format_bytes(total)}",
                                })

            state["stage"] = "extracting"
            state["percent"] = 100.0
            state["message"] = "Model paketi açılıyor ve etkinleştiriliyor..."

            part_file.replace(archive_file)
            await asyncio.to_thread(self._extract_archive, archive_file, dest_dir)
            archive_file.unlink(missing_ok=True)

            state["stage"] = "completed"
            state["message"] = "Kurulum tamamlandı!"
            self._loaded_models.pop(pack_id, None)
            self.invalidate_cache(pack_id)

        except asyncio.CancelledError:
            state["stage"] = "cancelled"
            state["message"] = "İndirme durduruldu."
            raise
        except Exception as exc:
            logger.exception("Dil modeli indirme hatası (%s): %s", pack_id, exc)
            state["stage"] = "error"
            state["message"] = f"Hata: {exc}"
        finally:
            await asyncio.sleep(1.5)
            if self._download_states.get(pack_id, {}).get("stage") in ("completed", "cancelled"):
                self._download_states.pop(pack_id, None)

    def _extract_archive(self, archive_file: Path, dest_dir: Path) -> None:
        tmp_dir = dest_dir.with_suffix(".tmp")
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_file, "r") as zf:
            zf.extractall(tmp_dir)
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        tmp_dir.replace(dest_dir)

    def _get_or_load_engine(self, pack_id: str) -> Dict[str, Any]:
        if pack_id in self._loaded_models:
            return self._loaded_models[pack_id]

        pack_dir = self.models_dir / pack_id
        if not self.is_pack_installed(pack_id):
            raise RuntimeError(f"'{pack_id}' çeviri modeli henüz indirilmemiş.")

        import ctranslate2
        import sentencepiece as spm

        model_bin = next(pack_dir.rglob("model.bin"))
        ct2_dir = str(model_bin.parent)
        sp_model_path = str(next(pack_dir.rglob("*.model")))

        translator = ctranslate2.Translator(ct2_dir, device="cpu", compute_type="int8")
        sp = spm.SentencePieceProcessor(model_file=sp_model_path)

        engine = {"translator": translator, "sp": sp}
        self._loaded_models[pack_id] = engine
        return engine

    def _run_single_model(self, text: str, pack_id: str) -> str:
        engine = self._get_or_load_engine(pack_id)
        translator = engine["translator"]
        sp = engine["sp"]

        paragraphs = text.splitlines()
        out_paragraphs = []

        for para in paragraphs:
            p_strip = para.strip()
            if not p_strip:
                out_paragraphs.append("")
                continue

            sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(p_strip) if s.strip()]
            if not sentences:
                out_paragraphs.append("")
                continue

            tokenized_batch = [sp.encode(s, out_type=str) for s in sentences]
            results = translator.translate_batch(
                tokenized_batch,
                beam_size=2,
                max_decoding_length=256,
            )
            decoded_sentences = [sp.decode(res.hypotheses[0]) for res in results]
            out_paragraphs.append(" ".join(decoded_sentences))

        return "\n".join(out_paragraphs)

    def translate_text(self, text: str, from_code: str = "en", to_code: str = "tr") -> Dict[str, Any]:
        t0 = time.monotonic()
        cleaned = text.strip()
        if not cleaned:
            return {"translated_text": "", "elapsed_ms": 0, "mode": "none"}

        from_code = from_code.lower().strip()
        to_code = to_code.lower().strip()

        if from_code == to_code:
            return {"translated_text": cleaned, "elapsed_ms": 0, "mode": "same_language"}

        # Doğrudan çift (ör. en_tr veya tr_en)
        direct_pack = f"{from_code}_{to_code}"
        if direct_pack in LANGUAGE_PACKS or self.is_pack_installed(direct_pack):
            if not self.is_pack_installed(direct_pack):
                lang_label = LANG_NAMES.get(to_code if from_code == "en" else from_code, direct_pack)
                raise RuntimeError(
                    f"'{lang_label}' çevrimdışı dil modeli henüz indirilmemiş. "
                    "Lütfen aşağıdaki 'Dil Paketleri' tablosundan veya Kurulum sayfasından ilgili dili indirin."
                )
            out_text = self._run_single_model(cleaned, direct_pack)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return {
                "translated_text": out_text,
                "elapsed_ms": elapsed_ms,
                "mode": f"neural_direct ({from_code}➔{to_code})",
            }

        # Köprü (Pivot) Çeviri: Kaynak Dil ➔ İngilizce (EN) ➔ Hedef Dil
        pack_step1 = f"{from_code}_en"
        pack_step2 = f"en_{to_code}"
        missing = []
        if not self.is_pack_installed(pack_step1):
            missing.append(LANG_NAMES.get(from_code, from_code))
        if not self.is_pack_installed(pack_step2):
            missing.append(LANG_NAMES.get(to_code, to_code))
        if missing:
            raise RuntimeError(
                f"{LANG_NAMES.get(from_code, from_code)} ➔ {LANG_NAMES.get(to_code, to_code)} çevirisi için "
                f"şu dil paketlerinin indirilmesi gerekiyor: {', '.join(missing)}."
            )

        mid_english = self._run_single_model(cleaned, pack_step1)
        final_text = self._run_single_model(mid_english, pack_step2)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return {
            "translated_text": final_text,
            "elapsed_ms": elapsed_ms,
            "mode": f"neural_pivot ({from_code}➔en➔{to_code})",
        }
