import os
import re
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

_CONF_CACHE: Dict[str, Any] = {"ts": 0.0, "items": []}
_INSTALLED_CACHE: Dict[str, Any] = {"ts": 0.0, "data": {}}
_PARTIAL_CACHE: Dict[str, Any] = {"ts": 0.0, "data": {}}


def invalidate_zim_scan_cache() -> None:
    _CONF_CACHE["ts"] = 0.0
    _INSTALLED_CACHE["ts"] = 0.0
    _PARTIAL_CACHE["ts"] = 0.0

# www/home/index.html ve config/content.conf içindeki bilinen paketlerin zengin meta verileri
KNOWN_METADATA: Dict[str, Dict[str, Any]] = {
    "wikipedia_tr_all_maxi": {
        "name": "Vikipedi (Türkçe)",
        "desc": "Türkçe Vikipedi'nin resimli tam kopyası.",
        "lang": "TR",
        "size": "~9 GB",
        "size_bytes": int(9 * 1024**3),
        "category": "Ansiklopedi",
        "search": True,
    },
    "wikipedia_en_all_maxi": {
        "name": "Wikipedia (English - Tam/Resimli)",
        "desc": "Tüm İngilizce Wikipedia, resimleriyle birlikte.",
        "lang": "EN",
        "size": "~120 GB",
        "size_bytes": int(120 * 1024**3),
        "category": "Ansiklopedi",
        "search": True,
    },
    "wikipedia_en_all_nopic": {
        "name": "Wikipedia (English - Resimsiz)",
        "desc": "İngilizce Wikipedia'nın resimsiz, küçük diskler için uygun sürümü.",
        "lang": "EN",
        "size": "~55 GB",
        "size_bytes": int(55 * 1024**3),
        "category": "Ansiklopedi",
        "search": True,
    },
    "wiktionary_tr_all_nopic": {
        "name": "Vikisözlük (Türkçe Wiktionary ZIM)",
        "desc": "Türkçe Vikisözlük tam arşivi: kelimeler, kökenler (etimoloji), deyimler ve çok dilli karşılıklar.",
        "lang": "TR",
        "size": "~810 MB",
        "size_bytes": int(810 * 1024**2),
        "category": "Türkçe Kitaplık",
        "search": True,
    },
    "wikibooks_tr_all_maxi": {
        "name": "Vikikitap (Türkçe)",
        "desc": "Açık ders kitapları, zanaat ve el rehberleri.",
        "lang": "TR",
        "size": "~27 MB",
        "size_bytes": int(27 * 1024**2),
        "category": "Türkçe Kitaplık",
        "search": True,
    },
    "wikisource_tr_all_maxi": {
        "name": "Vikikaynak (Türkçe)",
        "desc": "Telifsiz tarihi metinler, resmi kanunlar ve edebi klasikler.",
        "lang": "TR",
        "size": "~68 MB",
        "size_bytes": int(68 * 1024**2),
        "category": "Türkçe Kitaplık",
        "search": True,
    },
    "wikiquote_tr_all_maxi": {
        "name": "Vikisöz (Türkçe)",
        "desc": "Özlü sözler, alıntılar ve atasözleri arşivi.",
        "lang": "TR",
        "size": "~59 MB",
        "size_bytes": int(59 * 1024**2),
        "category": "Türkçe Kitaplık",
        "search": True,
    },
    "ifixit_tr_all": {
        "name": "iFixit (Türkçe)",
        "desc": "Cihaz, elektronik ve araç tamiri için Türkçe adım adım tamir rehberleri.",
        "lang": "TR",
        "size": "~3.6 GB",
        "size_bytes": int(3.6 * 1024**3),
        "category": "Türkçe Kitaplık",
        "search": True,
    },
    "phet_tr_all": {
        "name": "PhET Simülasyonları (Türkçe)",
        "desc": "Fizik, kimya, su ve matematik için çevrimdışı etkileşimli deney simülasyonları.",
        "lang": "TR",
        "size": "~107 MB",
        "size_bytes": int(107 * 1024**2),
        "category": "Türkçe Kitaplık",
        "search": False,
    },
    "wiktionary_en_all_nopic": {
        "name": "Wiktionary (English Tam ZIM)",
        "desc": "İngilizce Wiktionary tam arşivi: milyonlarca kelime, telaffuz ve tanım.",
        "lang": "EN",
        "size": "~8.5 GB",
        "size_bytes": int(8.5 * 1024**3),
        "category": "Sözlükler (ZIM Arşivleri)",
        "search": True,
    },
    "appropedia_en_all_maxi": {
        "name": "Appropedia",
        "desc": "Uygun teknoloji wiki'si: krizde su, güneş enerjisi, tarım ve barınak çözümleri.",
        "lang": "EN",
        "size": "~580 MB",
        "size_bytes": int(580 * 1024**2),
        "category": "Hayatta Kalma ve Hazırlık",
        "search": True,
    },
    "zimgit-post-disaster_en": {
        "name": "Afet Sonrası Kitaplığı",
        "desc": "Barınak, enerji, tarım ve yeniden yapılanma üzerine kitaplar.",
        "lang": "EN",
        "size": "~615 MB",
        "size_bytes": int(615 * 1024**2),
        "category": "Hayatta Kalma ve Hazırlık",
        "search": True,
    },
    "zimgit-water_en": {
        "name": "Su Arıtma",
        "desc": "İçme suyu bulma, arıtma ve saklama.",
        "lang": "EN",
        "size": "~20 MB",
        "size_bytes": int(20 * 1024**2),
        "category": "Hayatta Kalma ve Hazırlık",
        "search": False,
    },
    "zimgit-food-preparation_en": {
        "name": "Gıda Hazırlama ve Saklama",
        "desc": "Konserve, kurutma ve uzun süreli gıda saklama.",
        "lang": "EN",
        "size": "~93 MB",
        "size_bytes": int(93 * 1024**2),
        "category": "Hayatta Kalma ve Hazırlık",
        "search": False,
    },
    "zimgit-knots_en": {
        "name": "Düğümler Kitaplığı",
        "desc": "Düğüm çeşitleri ve kullanım alanları.",
        "lang": "EN",
        "size": "~27 MB",
        "size_bytes": int(27 * 1024**2),
        "category": "Hayatta Kalma ve Hazırlık",
        "search": False,
    },
    "ready.gov_en_all": {
        "name": "Ready.gov",
        "desc": "ABD resmi afet hazırlık rehberleri: deprem, sel, yangın.",
        "lang": "EN",
        "size": "~1.9 GB",
        "size_bytes": int(1.9 * 1024**3),
        "category": "Hayatta Kalma ve Hazırlık",
        "search": True,
    },
    "solar.lowtechmagazine.com_mul_all": {
        "name": "Low-tech Magazine",
        "desc": "Elektriksiz ve düşük teknolojili pratik çözümler.",
        "lang": "EN",
        "size": "~670 MB",
        "size_bytes": int(670 * 1024**2),
        "category": "Hayatta Kalma ve Hazırlık",
        "search": False,
    },
    "wikipedia_en_medicine_maxi": {
        "name": "WikiMed",
        "desc": "Wikipedia'nın tıp maddeleri: hastalıklar, ilaçlar, anatomi.",
        "lang": "EN",
        "size": "~2 GB",
        "size_bytes": int(2 * 1024**3),
        "category": "Sağlık ve İlk Yardım",
        "search": True,
    },
    "wikem_en_all_maxi": {
        "name": "WikEM",
        "desc": "Acil tıp başvuru kaynağı.",
        "lang": "EN",
        "size": "~260 MB",
        "size_bytes": int(260 * 1024**2),
        "category": "Sağlık ve İlk Yardım",
        "search": True,
    },
    "mdwiki_en_all_maxi": {
        "name": "MDWiki",
        "desc": "Doktorlar tarafından düzenlenen tıp ansiklopedisi.",
        "lang": "EN",
        "size": "~2.1 GB",
        "size_bytes": int(2.1 * 1024**3),
        "category": "Sağlık ve İlk Yardım",
        "search": True,
    },
    "medlineplus.gov_en_all": {
        "name": "MedlinePlus",
        "desc": "ABD Ulusal Tıp Kütüphanesi (NLM) resmi hasta bilgilendirme ve tedavi arşivi.",
        "lang": "EN",
        "size": "~1.9 GB",
        "size_bytes": int(1.9 * 1024**3),
        "category": "Sağlık ve İlk Yardım",
        "search": True,
    },
    "zimgit-medicine_en": {
        "name": "Tıp Kitaplığı",
        "desc": "Temel tıp ve sağlık kitapları.",
        "lang": "EN",
        "size": "~67 MB",
        "size_bytes": int(67 * 1024**2),
        "category": "Sağlık ve İlk Yardım",
        "search": False,
    },
    "fas-military-medicine_en": {
        "name": "Askeri Sahra Tıbbı",
        "desc": "Sahada travma ve yaralı bakımı.",
        "lang": "EN",
        "size": "~72 MB",
        "size_bytes": int(72 * 1024**2),
        "category": "Sağlık ve İlk Yardım",
        "search": False,
    },
    "irp.fas.org_en_military-medicine": {
        "name": "Askeri Sahra Tıbbı",
        "desc": "Sahada travma ve yaralı bakımı.",
        "lang": "EN",
        "size": "~72 MB",
        "size_bytes": int(72 * 1024**2),
        "category": "Sağlık ve İlk Yardım",
        "search": False,
    },
    "nhs.uk_en_medicines": {
        "name": "NHS İlaç Rehberi",
        "desc": "İlaçların kullanımı, dozları ve yan etkileri.",
        "lang": "EN",
        "size": "~15 MB",
        "size_bytes": int(15 * 1024**2),
        "category": "Sağlık ve İlk Yardım",
        "search": False,
    },
    "ifixit_en_all": {
        "name": "iFixit",
        "desc": "Cihaz ve araç tamiri için adım adım rehberler.",
        "lang": "EN",
        "size": "~3 GB",
        "size_bytes": int(3 * 1024**3),
        "category": "Tamir ve Beceriler",
        "search": True,
    },
    "diy.stackexchange.com_en_all": {
        "name": "Ev Tamiri (DIY)",
        "desc": "Elektrik, tesisat ve yapı soruları.",
        "lang": "EN",
        "size": "~1.2 GB",
        "size_bytes": int(1.2 * 1024**3),
        "category": "Tamir ve Beceriler",
        "search": False,
    },
    "gardening.stackexchange.com_en_all": {
        "name": "Bahçecilik",
        "desc": "Sebze yetiştirme, toprak ve bitki hastalıkları.",
        "lang": "EN",
        "size": "~500 MB",
        "size_bytes": int(500 * 1024**2),
        "category": "Tamir ve Beceriler",
        "search": False,
    },
    "cooking.stackexchange.com_en_all": {
        "name": "Yemek Pişirme",
        "desc": "Pişirme teknikleri ve gıda güvenliği.",
        "lang": "EN",
        "size": "~350 MB",
        "size_bytes": int(350 * 1024**2),
        "category": "Tamir ve Beceriler",
        "search": False,
    },
    "ham.stackexchange.com_en_all": {
        "name": "Amatör Telsiz",
        "desc": "Telsiz kurulumu, anten ve haberleşme.",
        "lang": "EN",
        "size": "~250 MB",
        "size_bytes": int(250 * 1024**2),
        "category": "Tamir ve Beceriler",
        "search": False,
    },
    "mechanics.stackexchange.com_en_all": {
        "name": "Araç Bakımı",
        "desc": "Motor, fren ve araç arızaları.",
        "lang": "EN",
        "size": "~450 MB",
        "size_bytes": int(450 * 1024**2),
        "category": "Tamir ve Beceriler",
        "search": False,
    },
    "outdoors.stackexchange.com_en_all": {
        "name": "Doğa ve Kamp",
        "desc": "Kamp, yürüyüş ve doğada hayatta kalma.",
        "lang": "EN",
        "size": "~200 MB",
        "size_bytes": int(200 * 1024**2),
        "category": "Tamir ve Beceriler",
        "search": False,
    },
    "sustainability.stackexchange.com_en_all": {
        "name": "Sürdürülebilirlik",
        "desc": "Enerji, su ve kaynak tasarrufu.",
        "lang": "EN",
        "size": "~100 MB",
        "size_bytes": int(100 * 1024**2),
        "category": "Tamir ve Beceriler",
        "search": False,
    },
    "survivorlibrary.com_en_all": {
        "name": "Survivor Library (Tam Arşiv)",
        "desc": "Tarihi el kitapları, zanaat, tarım ve mühendislik arşivi (512 GB+ disk önerilir).",
        "lang": "EN",
        "size": "~205 GB",
        "size_bytes": int(205 * 1024**3),
        "category": "Büyük ve İsteğe Bağlı Arşivler",
        "search": True,
    },
    "wikivoyage_en_all_maxi": {
        "name": "Wikivoyage (Seyahat Rehberi)",
        "desc": "Dünya genelinde çevrimdışı seyahat ve bölge rehberi.",
        "lang": "EN",
        "size": "~1.2 GB",
        "size_bytes": int(1.2 * 1024**3),
        "category": "Büyük ve İsteğe Bağlı Arşivler",
        "search": True,
    },
}

VALID_KIWIX_FOLDERS = {
    "wikipedia", "other", "zimit", "ifixit", "stack_exchange",
    "wikivoyage", "gutenberg", "ted", "phet", "vikidia",
    "wiktionary", "wikibooks", "wikisource", "wikiversity", "wikiquote",
}

LINE_RE = re.compile(
    r"^\s*(?P<commented>#\s*)?(?P<folder>[a-z_]+)\s+(?P<prefix>[a-zA-Z0-9._-]+)(?:\s+#\s*(?P<note>.*))?$"
)
SIZE_RE = re.compile(r"~\s*([\d.,]+)\s*(GB|MB)", re.IGNORECASE)


def parse_size_from_note(note: str) -> tuple[str, int]:
    if not note:
        return "—", 0
    m = SIZE_RE.search(note)
    if not m:
        return "—", 0
    val_str = m.group(1).replace(",", ".")
    unit = m.group(2).upper()
    try:
        val = float(val_str)
        mult = 1024**3 if unit == "GB" else 1024**2
        return f"~{m.group(1)} {unit}", int(val * mult)
    except ValueError:
        return "—", 0


def parse_content_conf(conf_path: Path) -> List[Dict[str, Any]]:
    """
    config/content.conf dosyasını okur; hem aktif hem de '#' ile yorum satırı yapılmış
    isteğe bağlı paketleri ayrıştırır.
    """
    now = time.monotonic()
    if _CONF_CACHE["items"] and (now - _CONF_CACHE["ts"] < 5.0):
        return _CONF_CACHE["items"]

    items: List[Dict[str, Any]] = []
    current_category = "Diğer Kaynaklar"

    if not conf_path.exists():
        return items

    for raw_line in conf_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue

        # Kategori başlığı kontrolü: # --- Ansiklopedi / Encyclopedia ---
        if stripped.startswith("# ---") and stripped.endswith("---"):
            header = stripped.strip("# -").split("/")[0].strip()
            if header:
                current_category = header
            continue

        m = LINE_RE.match(raw_line)
        if not m:
            continue

        folder = m.group("folder")
        prefix = m.group("prefix")
        if folder not in VALID_KIWIX_FOLDERS:
            continue

        enabled_in_conf = m.group("commented") is None
        note = (m.group("note") or "").strip()

        meta = KNOWN_METADATA.get(prefix, {})
        note_size_str, note_size_bytes = parse_size_from_note(note)

        lang = meta.get("lang")
        if not lang:
            if "_tr" in prefix:
                lang = "TR"
            elif "_en" in prefix:
                lang = "EN"
            else:
                lang = "—"

        items.append({
            "id": prefix,
            "prefix": prefix,
            "folder": folder,
            "name": meta.get("name", prefix),
            "desc": meta.get("desc", note or f"{folder}/{prefix}"),
            "lang": lang,
            "size": meta.get("size", note_size_str),
            "size_bytes": meta.get("size_bytes", note_size_bytes),
            "category": meta.get("category", current_category),
            "search": meta.get("search", False),
            "enabled_in_conf": enabled_in_conf,
        })

    _CONF_CACHE["ts"] = now
    _CONF_CACHE["items"] = items
    return items


def update_content_conf(conf_path: Path, selected_prefixes: set[str]) -> None:
    """
    Kullanıcının Web arayüzünde seçtiği paketlere göre config/content.conf dosyasındaki
    yorum işaretlerini (#) günceller; böylece CLI betiği ve Web UI senkronize kalır.
    """
    if not conf_path.exists():
        return

    new_lines: List[str] = []
    for raw_line in conf_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE_RE.match(raw_line)
        if m and m.group("folder") in VALID_KIWIX_FOLDERS:
            folder = m.group("folder")
            prefix = m.group("prefix")
            note = m.group("note")
            comment_part = f"  # {note}" if note else ""
            if prefix in selected_prefixes:
                new_lines.append(f"{folder:<15} {prefix:<38}{comment_part}".rstrip())
            else:
                new_lines.append(f"# {folder:<13} {prefix:<38}{comment_part}".rstrip())
        else:
            new_lines.append(raw_line)

    conf_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    _CONF_CACHE["ts"] = 0.0


def scan_installed_zims(zim_dir: Path) -> Dict[str, Dict[str, Any]]:
    """
    /library/zims/content altındaki mevcut .zim ve .zim.part dosyalarını tarar.
    Dönüş: { "wikipedia_tr_all_maxi": { "filename": "...", "version": "2026-09", "size_bytes": 1234 } }
    """
    now = time.monotonic()
    if _INSTALLED_CACHE["ts"] > 0 and (now - _INSTALLED_CACHE["ts"] < 3.0):
        return _INSTALLED_CACHE["data"]

    installed: Dict[str, Dict[str, Any]] = {}
    if not zim_dir.exists():
        return installed

    zim_re = re.compile(r"^(?P<prefix>.+?)_(?P<year>\d{4})-(?P<month>\d{2})[a-z]?\.zim$")

    for f in sorted(zim_dir.glob("*.zim")):
        if not f.is_file():
            continue
        stat = f.stat()
        m = zim_re.match(f.name)
        if m:
            prefix = m.group("prefix")
            version = f"{m.group('month')}/{m.group('year')}"
            book_id = f.stem
        else:
            prefix = f.stem
            version = "Kurulu"
            book_id = f.stem

        installed[prefix] = {
            "filename": f.name,
            "book_id": book_id,
            "version": version,
            "size_bytes": stat.st_size,
            "href": f"/kiwix/{book_id}",
        }

    _INSTALLED_CACHE["ts"] = now
    _INSTALLED_CACHE["data"] = installed
    return installed


def scan_partial_zims(zim_dir: Path) -> Dict[str, Dict[str, Any]]:
    """
    Yarım kalmış (.zim.part) dosyalarını tarar.
    """
    now = time.monotonic()
    if _PARTIAL_CACHE["ts"] > 0 and (now - _PARTIAL_CACHE["ts"] < 3.0):
        return _PARTIAL_CACHE["data"]

    partials: Dict[str, Dict[str, Any]] = {}
    if not zim_dir.exists():
        return partials

    part_re = re.compile(r"^(?P<prefix>.+?)_(?P<year>\d{4})-(?P<month>\d{2})[a-z]?\.zim\.part$")
    for f in sorted(zim_dir.glob("*.zim.part")):
        if not f.is_file():
            continue
        stat = f.stat()
        m = part_re.match(f.name)
        prefix = m.group("prefix") if m else f.name.replace(".zim.part", "")
        partials[prefix] = {
            "filename": f.name,
            "downloaded_bytes": stat.st_size,
        }
    _PARTIAL_CACHE["ts"] = now
    _PARTIAL_CACHE["data"] = partials
    return partials
