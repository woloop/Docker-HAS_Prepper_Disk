import asyncio
import base64
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from xml.sax.saxutils import escape as xml_escape

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from app.config_parser import (
    KNOWN_METADATA,
    invalidate_zim_scan_cache,
    parse_content_conf,
    scan_installed_zims,
    scan_partial_zims,
    update_content_conf,
)
from app.dictionary import DictionaryManager
from app.downloader import DownloadManager, format_bytes
from app.kiwix_manager import KiwixManager
from app.translator import LocalTranslator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("prepper.main")

# -------------------------------------------------------------------------
# Kiwix Makale İçi Üst Çubuk & Seç-Çevir / Sözlük Betiği (/api/kiwix-helper.js)
# -------------------------------------------------------------------------

KIWIX_HELPER_JS = r"""
(function(){
  if (window.__hasPrepperKiwixHelperLoaded) return;
  window.__hasPrepperKiwixHelperLoaded = true;

  const style = document.createElement("style");
  style.textContent = `
    #prepper-kiwix-bar {
      position: sticky;
      top: 0;
      left: 0;
      right: 0;
      z-index: 2147483640;
      background: linear-gradient(#3F7FAD, #006699);
      color: #fff;
      border-bottom: 2px solid #FFA34F;
      font-family: Verdana, Tahoma, Arial, sans-serif !important;
      font-size: 11px !important;
      line-height: 1.4 !important;
      padding: 4px 10px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 6px;
      box-shadow: 0 2px 6px rgba(0,0,0,0.22);
    }
    #prepper-kiwix-bar a {
      color: #fff !important;
      text-decoration: none !important;
      font-weight: bold !important;
      margin-right: 8px;
      font-size: 11px !important;
    }
    #prepper-kiwix-bar a:hover {
      color: #FFA34F !important;
      text-decoration: underline !important;
    }
    #prepper-kiwix-bar .pk-brand {
      font-family: "Trebuchet MS", Verdana, sans-serif !important;
      font-size: 14px !important;
      font-weight: bold !important;
      color: #fff !important;
      margin-right: 10px;
    }
    #prepper-kiwix-bar .pk-brand span {
      color: #FFA34F !important;
    }
    #prepper-kiwix-bar .pk-btn {
      background: #FAFAFA;
      color: #000 !important;
      border: 1px solid #003F5E;
      padding: 2px 7px;
      font-family: Verdana, sans-serif !important;
      font-size: 10px !important;
      font-weight: bold !important;
      cursor: pointer;
      border-radius: 2px;
    }
    #prepper-kiwix-bar .pk-btn:hover {
      background: #FFF3D6;
      color: #006699 !important;
    }
    #prepper-sel-tooltip {
      position: fixed;
      z-index: 2147483645;
      display: none;
      background: #EFEFEF;
      border: 2px solid #006699;
      padding: 4px;
      box-shadow: 0 3px 10px rgba(0,0,0,0.3);
      font-family: Verdana, sans-serif !important;
      font-size: 11px !important;
      gap: 4px;
      align-items: center;
    }
    #prepper-sel-tooltip button {
      background: linear-gradient(#3F7FAD, #006699);
      color: #fff;
      border: 1px solid #003F5E;
      padding: 3px 7px;
      font-family: Verdana, sans-serif !important;
      font-size: 10px !important;
      font-weight: bold;
      cursor: pointer;
    }
    #prepper-sel-tooltip button:hover {
      color: #FFA34F;
    }
    #prepper-popup-card {
      position: fixed;
      right: 16px;
      bottom: 16px;
      width: 390px;
      max-width: calc(100vw - 24px);
      max-height: 75vh;
      z-index: 2147483646;
      display: none;
      background: #fff;
      border: 2px solid #006699;
      box-shadow: 0 5px 18px rgba(0,0,0,0.35);
      font-family: Verdana, Tahoma, Arial, sans-serif !important;
      font-size: 11px !important;
      color: #000 !important;
      flex-direction: column;
    }
    #prepper-popup-head {
      background: linear-gradient(#3F7FAD, #006699);
      color: #FFA34F;
      font-weight: bold;
      padding: 5px 8px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 11px !important;
    }
    #prepper-popup-body {
      padding: 8px;
      overflow-y: auto;
      background: #EFEFEF;
      max-height: 58vh;
    }
    .pk-input-row {
      display: flex;
      gap: 4px;
      margin-bottom: 6px;
    }
    .pk-input-row input {
      flex: 1;
      font-family: Verdana, sans-serif !important;
      font-size: 11px !important;
      padding: 3px 5px;
      border: 1px solid #7F9DB9;
      background: #fff;
      color: #000;
    }
    .pk-table {
      width: 100%;
      border-collapse: collapse;
      border: 1px solid #006699;
      background: #fff;
      margin-top: 4px;
    }
    .pk-table th {
      background: #C7D0D7;
      color: #006699;
      padding: 3px 5px;
      font-size: 10px;
      text-align: left;
      border: 1px solid #fff;
    }
    .pk-table td {
      padding: 4px 6px;
      border: 1px solid #DEE3E7;
      font-size: 11px;
      color: #000;
    }
  `;
  document.head.appendChild(style);

  const bar = document.createElement("div");
  bar.id = "prepper-kiwix-bar";
  bar.innerHTML = `
    <div style="display:flex;align-items:center;flex-wrap:wrap;gap:4px">
      <a href="/home" class="pk-brand" style="margin-right:2px">HAS_<span>Prepper</span>Disk</a>
      <span style="font-size:9px;font-weight:bold;color:#FFA34F;background:rgba(0,0,0,0.25);border:1px solid rgba(255,163,79,0.5);border-radius:2px;padding:1px 5px;margin-right:6px;letter-spacing:0.5px">🐳 DOCKERIZED</span>
      <a href="/home">» Ana Sayfa</a>
      <a href="/dictionary">» Sözlük</a>
      <a href="/translate">» Çeviri</a>
      <a href="/docs">» Belgeler</a>
      <a href="/setup">» Kurulum</a>
    </div>
    <div style="display:flex;align-items:center;gap:5px;flex-wrap:wrap">
      <span style="font-size:10px;color:#DCE7F0" class="pk-hint">💡 Metni seçip anında çevirebilir / sözlükte arayabilirsiniz</span>
      <button type="button" class="pk-btn" id="pk-open-helper">📖 Hızlı Sözlük &amp; Çeviri</button>
      <button type="button" class="pk-btn" id="pk-bookmark-btn">⭐ Yer İmlerine Ekle</button>
    </div>
  `;
  if (document.body) {
    document.body.insertBefore(bar, document.body.firstChild);
  } else {
    document.addEventListener("DOMContentLoaded", () => {
      document.body.insertBefore(bar, document.body.firstChild);
    });
  }

  const tooltip = document.createElement("div");
  tooltip.id = "prepper-sel-tooltip";
  tooltip.innerHTML = `
    <button type="button" id="pk-sel-dict">📖 Sözlükte Bak</button>
    <button type="button" id="pk-sel-tr">🌐 Türkçeye Çevir</button>
    <button type="button" id="pk-sel-note">📝 Notlara Kaydet</button>
  `;
  document.body.appendChild(tooltip);

  const card = document.createElement("div");
  card.id = "prepper-popup-card";
  card.innerHTML = `
    <div id="prepper-popup-head">
      <span id="prepper-popup-title">HAS_PrepperDisk :: Makale İçi Sözlük &amp; Çeviri</span>
      <button type="button" id="prepper-popup-close" style="background:#990000;color:#fff;border:1px solid #fff;font-weight:bold;cursor:pointer;font-size:10px;padding:1px 6px">✕ Kapat</button>
    </div>
    <div id="prepper-popup-body">
      <div class="pk-input-row">
        <input type="text" id="pk-query-input" placeholder="Kelime veya cümle yazın...">
        <button type="button" class="pk-btn" id="pk-do-dict">Sözlük</button>
        <button type="button" class="pk-btn" id="pk-do-tr">Çevir</button>
      </div>
      <div id="pk-result-area" style="font-size:11px;color:#222">
        Sayfadaki herhangi bir İngilizce kelimeyi veya cümleyi fareyle seçtiğinizde burada Türkçe anlamını görebilirsiniz.
      </div>
    </div>
  `;
  document.body.appendChild(card);

  const esc = s => String(s || "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  let lastSelectedText = "";

  function showCard(titleText) {
    card.style.display = "flex";
    if (titleText) document.getElementById("prepper-popup-title").textContent = titleText;
  }

  async function lookupDict(text) {
    const clean = (text || "").trim();
    if (!clean) return;
    document.getElementById("pk-query-input").value = clean;
    showCard("📖 Çevrimdışı Sözlük Sonucu");
    const area = document.getElementById("pk-result-area");
    area.innerHTML = "<i>Sözlükte aranıyor...</i>";
    try {
      const r = await fetch(`/api/dictionary/search?q=${encodeURIComponent(clean)}&limit=20`);
      const data = await r.json();
      const rows = data.items || data.results || [];
      if (!rows.length) {
        area.innerHTML = `<div style="padding:6px;background:#FFF3CD;border:1px solid #FFEEBA"><b>"${esc(clean)}"</b> için tam kelime eşleşmesi bulunamadı. <button type="button" class="pk-btn" id="pk-fallback-tr">🌐 Cümle Çevirisi Dene</button></div>`;
        const fb = document.getElementById("pk-fallback-tr");
        if (fb) fb.onclick = () => translateSelection(clean);
        return;
      }
      rows.sort((a, b) => {
        const aTr = String(a.lang_pair || a.direction || "").includes("TR") ? 0 : 1;
        const bTr = String(b.lang_pair || b.direction || "").includes("TR") ? 0 : 1;
        return aTr - bTr;
      });
      let html = `<table class="pk-table"><tr><th>Kelime</th><th>Yön</th><th>Anlamı / Karşılığı</th></tr>`;
      for (const item of rows) {
        const hw = item.headword || item.word || "";
        const lp = item.lang_pair || item.direction || "";
        const def = item.definition || item.translation || "";
        html += `<tr><td><b>${esc(hw)}</b></td><td style="font-size:10px;color:#006699;white-space:nowrap">${esc(lp)}</td><td>${esc(def)}</td></tr>`;
      }
      html += `</table>`;
      area.innerHTML = html;
    } catch (e) {
      area.innerHTML = `<span style="color:#990000">Sözlük sorgu hatası: ${esc(e.message)}</span>`;
    }
  }

  async function translateSelection(text) {
    const clean = (text || "").trim();
    if (!clean) return;
    document.getElementById("pk-query-input").value = clean;
    showCard("🌐 Çevrimdışı Yapay Zeka Çevirisi (EN ➔ TR)");
    const area = document.getElementById("pk-result-area");
    area.innerHTML = "<i>Çevrimdışı sinirsel model ile çevriliyor...</i>";
    try {
      const r = await fetch("/api/translate", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ text: clean, from_code: "en", to_code: "tr" })
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "Çeviri yapılamadı");
      area.innerHTML = `
        <div style="background:#fff;border:1px solid #98AAB1;padding:6px;margin-bottom:5px">
          <div style="font-size:10px;color:#666;margin-bottom:2px"><b>Kaynak Metin:</b></div>
          <div>${esc(clean)}</div>
        </div>
        <div style="background:#FFF8E6;border:1px solid #006699;padding:6px">
          <div style="font-size:10px;color:#006699;margin-bottom:2px"><b>Türkçe Çevirisi (${esc(data.engine || "Argos")}):</b></div>
          <div style="font-weight:bold;font-size:12px">${esc(data.translated_text)}</div>
        </div>
      `;
    } catch (e) {
      area.innerHTML = `<span style="color:#990000">Çeviri hatası: ${esc(e.message)}</span>`;
    }
  }

  async function saveQuoteToNotes(text) {
    const clean = (text || "").trim();
    if (!clean) return;
    showCard("📝 Saha Notlarına Kaydedildi");
    const area = document.getElementById("pk-result-area");
    area.innerHTML = "<i>Notlara kaydediliyor...</i>";
    try {
      const pageTitle = document.title || location.pathname;
      const r = await fetch("/api/notes/items", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          title: `Kütüphane Alıntısı: ${pageTitle.slice(0, 60)}`,
          author: "Kütüphane Okuyucu",
          category: "Kütüphane Alıntısı",
          content: `"${clean}"\n\nKaynak: ${location.pathname}${location.search}`,
          pinned: false
        })
      });
      if (!r.ok) throw new Error("Kaydedilemedi");
      area.innerHTML = `<div style="padding:6px;background:#D4EDDA;border:1px solid #A3CFBB;color:#155724">✓ Seçilen metin <b><a href="/tools#notes" style="color:#155724">/tools#notes</a></b> defterine kaydedildi!</div>`;
    } catch (e) {
      area.innerHTML = `<span style="color:#990000">Hata: ${esc(e.message)}</span>`;
    }
  }

  document.getElementById("pk-open-helper").addEventListener("click", () => {
    showCard("HAS_PrepperDisk :: Makale İçi Sözlük & Çeviri");
    document.getElementById("pk-query-input").focus();
  });

  document.getElementById("prepper-popup-close").addEventListener("click", () => {
    card.style.display = "none";
  });

  document.getElementById("pk-do-dict").addEventListener("click", () => {
    lookupDict(document.getElementById("pk-query-input").value);
  });

  document.getElementById("pk-do-tr").addEventListener("click", () => {
    translateSelection(document.getElementById("pk-query-input").value);
  });

  document.getElementById("pk-query-input").addEventListener("keydown", e => {
    if (e.key === "Enter") {
      e.preventDefault();
      const val = e.target.value.trim();
      if (val.split(/\s+/).length <= 2) lookupDict(val);
      else translateSelection(val);
    }
  });

  document.getElementById("pk-bookmark-btn").addEventListener("click", async function() {
    const btn = this;
    try {
      const r = await fetch("/api/notes/bookmarks", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          title: document.title || location.pathname,
          url: location.pathname + location.search,
          category: "Kütüphane",
          note: "Kiwix makale içi üst çubuktan eklendi."
        })
      });
      if (r.ok) {
        btn.textContent = "✓ Yer İmlerine Eklendi";
        setTimeout(() => { btn.textContent = "⭐ Yer İmlerine Ekle"; }, 2500);
      }
    } catch (e) {}
  });

  document.getElementById("pk-sel-dict").addEventListener("mousedown", e => {
    e.preventDefault();
    e.stopPropagation();
    tooltip.style.display = "none";
    lookupDict(lastSelectedText);
  });

  document.getElementById("pk-sel-tr").addEventListener("mousedown", e => {
    e.preventDefault();
    e.stopPropagation();
    tooltip.style.display = "none";
    translateSelection(lastSelectedText);
  });

  document.getElementById("pk-sel-note").addEventListener("mousedown", e => {
    e.preventDefault();
    e.stopPropagation();
    tooltip.style.display = "none";
    saveQuoteToNotes(lastSelectedText);
  });

  function handleSelectionChange(ev) {
    if (card.contains(ev.target) || tooltip.contains(ev.target) || bar.contains(ev.target)) return;
    setTimeout(() => {
      const sel = window.getSelection ? window.getSelection() : null;
      const text = sel ? sel.toString().trim() : "";
      if (text && text.length >= 2 && text.length <= 800) {
        lastSelectedText = text;
        let x = ev.clientX || (window.innerWidth / 2);
        let y = (ev.clientY || 100) + 14;
        if (x + 290 > window.innerWidth) x = Math.max(8, window.innerWidth - 300);
        if (y + 50 > window.innerHeight) y = Math.max(40, y - 48);
        tooltip.style.left = x + "px";
        tooltip.style.top = y + "px";
        tooltip.style.display = "flex";
      } else {
        tooltip.style.display = "none";
      }
    }, 20);
  }

  document.addEventListener("mouseup", handleSelectionChange);
  document.addEventListener("touchend", handleSelectionChange);
})();
"""


# -------------------------------------------------------------------------
# Notlar, Yer İmleri ve Kişisel Belge Kitaplığı Yöneticileri
# -------------------------------------------------------------------------

STARTER_BOOKMARKS = [
    {
        "title": "Su Arıtma ve İçme Suyu Hazırlama (Water Purification)",
        "url": "/kiwix/zimgit-water_en_2024-08/",
        "category": "Su & Gıda",
        "note": "Kaynatma, klorlama ve filtreleme yöntemleri kütüphane kitabı.",
    },
    {
        "title": "Temel Düğümler ve Bağlama Teknikleri (Knots)",
        "url": "/kiwix/zimgit-knots_en_2024-08/",
        "category": "Kamp & Barınak",
        "note": "Barınak kurma, kurtarma ve yük sabitleme düğümleri.",
    },
    {
        "title": "Askeri Sahra Tıbbı ve Travma Müdahalesi",
        "url": "/kiwix/irp.fas.org_en_military-medicine_2025-12/",
        "category": "Sağlık & İlk Yardım",
        "note": "Kanama kontrolü, turnike, kırık sabitleme ve şok tedavisi.",
    },
    {
        "title": "Afet Sonrası Yeniden Yapılanma Kitaplığı (Post-Disaster)",
        "url": "/kiwix/zimgit-post-disaster_en_2024-05/",
        "category": "Hayatta Kalma",
        "note": "Barınak, enerji, tarım ve temel mühendislik rehberleri.",
    },
]

STARTER_NOTES = [
    {
        "title": "72 Saatlik Acil Durum Çantası Kontrol Listesi",
        "author": "Sistem Rehberi",
        "category": "Kontrol Listesi",
        "pinned": 1,
        "content": (
            "• Su ve Gıda: Kişi başı günlük 3 L su, klor/çamaşır suyu, konserve ve enerji barı.\n"
            "• İlk Yardım: Turnike, gazlı bez, antiseptik, ORS tuz-şeker paketi, reçeteli ilaçlar.\n"
            "• Haberleşme & Enerji: PMR446 el telsizi (Kanal 8 acil çağrı), kafa feneri, dolu powerbank.\n"
            "• Ekipman: Çakı, paracord ip, çakmak, düdük, termal battaniye, kimlik fotokopileri."
        ),
    },
]

STARTER_DOCS = [
    {
        "filename": "Acil_Durum_Telsiz_ve_Haberlesme_Rehberi.md",
        "title": "Acil Durum Telsiz (PMR446 / Amatör) ve Haberleşme Rehberi",
        "category": "Haberleşme",
        "description": "PMR446 frekansları, acil durum çağrı protokolleri ve NATO fonetik alfabesi.",
        "content": """# Acil Durum Telsiz ve Haberleşme Rehberi

## 1. PMR446 Lisanssız El Telsizi Frekansları
- **Kanal 1 (446.00625 MHz):** Genel çağrı ve yerel grup iletişimi
- **Kanal 3 (446.03125 MHz):** Hazırlık (Prepper) saha kanalı
- **Kanal 8 (446.09375 MHz):** **Acil Durum ve Dağ/Doğa Yardım Kanalı**

## 2. Acil Çağrı Protokolü (MAYDAY)
1. Telsizde **3 kez "MAYDAY"** deyin.
2. **İsminizi**, **konumunuzu** ve **acil durumun niteliğini** net biçimde belirtin.
""",
    },
    {
        "filename": "Field_Water_and_Medical_Quick_Guide_EN.txt",
        "title": "Field Water Disinfection & First Aid Quick Reference (English)",
        "category": "Sağlık & Su",
        "description": "İngilizce saha su arıtma ve ilk yardım özet belgesi ('Çevir' butonuyla Türkçeye çevirebilirsiniz).",
        "content": """FIELD WATER DISINFECTION AND FIRST AID QUICK REFERENCE

1. WATER PURIFICATION IN EMERGENCIES
Boiling is the surest method to make water safer to drink by killing disease-causing microorganisms.
- Bring clear water to a rolling boil for 1 full minute (at elevations above 2,000 meters, boil for 3 minutes).

2. CHEMICAL DISINFECTION WITH HOUSEHOLD BLEACH
- For 1 Liter of clear water with 5% to 6% sodium hypochlorite bleach: add 2 drops of bleach.
- For cloudy or very cold water: double the dose to 4 drops per liter and let stand for 30 minutes.
""",
    },
]


class NotesAndBookmarksManager:
    def __init__(self, notes_dir: Path):
        self.notes_dir = notes_dir
        self.db_path = self.notes_dir / "notes.db"
        self.tmp_dir = Path(tempfile.gettempdir()) / "prepper_notes_cache"
        self.tmp_db_path = self.tmp_dir / "notes.db"
        self._lock = threading.Lock()
        self._initialized = False

    def _ensure_db(self) -> Path:
        with self._lock:
            self.notes_dir.mkdir(parents=True, exist_ok=True)
            self.tmp_dir.mkdir(parents=True, exist_ok=True)

            if self.db_path.exists() and not self.tmp_db_path.exists():
                shutil.copyfile(self.db_path, self.tmp_db_path)

            if not self._initialized or not self.tmp_db_path.exists():
                conn = sqlite3.connect(self.tmp_db_path)
                try:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS bookmarks (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            title TEXT NOT NULL,
                            url TEXT NOT NULL,
                            category TEXT NOT NULL DEFAULT 'Genel',
                            note TEXT NOT NULL DEFAULT '',
                            created_at TEXT NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS notes (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            title TEXT NOT NULL,
                            author TEXT NOT NULL DEFAULT 'Kullanıcı',
                            category TEXT NOT NULL DEFAULT 'Genel',
                            content TEXT NOT NULL,
                            pinned INTEGER NOT NULL DEFAULT 0,
                            created_at TEXT NOT NULL
                        )
                        """
                    )
                    cur = conn.execute("SELECT COUNT(*) FROM bookmarks")
                    if cur.fetchone()[0] == 0:
                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                        for b in STARTER_BOOKMARKS:
                            conn.execute(
                                "INSERT INTO bookmarks (title, url, category, note, created_at) VALUES (?, ?, ?, ?, ?)",
                                (b["title"], b["url"], b["category"], b["note"], now_str),
                            )
                    else:
                        conn.execute(
                            "UPDATE bookmarks SET url = REPLACE(url, '/kiwix/content/', '/kiwix/') WHERE url LIKE '/kiwix/content/%'"
                        )

                    cur = conn.execute("SELECT COUNT(*) FROM notes")
                    if cur.fetchone()[0] == 0:
                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                        for n in STARTER_NOTES:
                            conn.execute(
                                "INSERT INTO notes (title, author, category, content, pinned, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                                (n["title"], n["author"], n["category"], n["content"], n["pinned"], now_str),
                            )
                    conn.commit()
                finally:
                    conn.close()

                shutil.copyfile(self.tmp_db_path, self.db_path)
                self._initialized = True

            return self.tmp_db_path

    def _sync_to_library(self) -> None:
        try:
            self.notes_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.tmp_db_path, self.db_path)
        except Exception as exc:
            logger.warning("Not veritabanı senkronizasyon uyarısı: %s", exc)

    def get_all(self, q: str = "", category: str = "all") -> Dict[str, Any]:
        db_file = self._ensure_db()
        query = (q or "").strip().lower()
        cat = (category or "all").strip()

        conn = sqlite3.connect(db_file)
        try:
            bm_rows = conn.execute(
                "SELECT id, title, url, category, note, created_at FROM bookmarks ORDER BY id DESC"
            ).fetchall()
            note_rows = conn.execute(
                "SELECT id, title, author, category, content, pinned, created_at FROM notes ORDER BY pinned DESC, id DESC"
            ).fetchall()
        finally:
            conn.close()

        bookmarks = []
        for r in bm_rows:
            item = {
                "id": r[0],
                "title": r[1],
                "url": r[2],
                "category": r[3],
                "note": r[4],
                "created_at": r[5],
            }
            if cat != "all" and item["category"] != cat:
                continue
            if query and query not in item["title"].lower() and query not in item["note"].lower() and query not in item["url"].lower():
                continue
            bookmarks.append(item)

        notes = []
        for r in note_rows:
            item = {
                "id": r[0],
                "title": r[1],
                "author": r[2],
                "category": r[3],
                "content": r[4],
                "pinned": bool(r[5]),
                "created_at": r[6],
            }
            if cat != "all" and item["category"] != cat:
                continue
            if query and query not in item["title"].lower() and query not in item["content"].lower():
                continue
            notes.append(item)

        return {
            "bookmarks": bookmarks,
            "notes": notes,
            "bookmark_count": len(bookmarks),
            "note_count": len(notes),
        }

    def add_bookmark(self, title: str, url: str, category: str = "Genel", note: str = "") -> Dict[str, Any]:
        db_file = self._ensure_db()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        clean_title = (title or url or "Kütüphane Bağlantısı").strip()
        clean_url = (url or "/kiwix/").strip()
        clean_cat = (category or "Genel").strip()
        clean_note = (note or "").strip()

        with self._lock:
            conn = sqlite3.connect(db_file)
            try:
                cur = conn.execute(
                    "INSERT INTO bookmarks (title, url, category, note, created_at) VALUES (?, ?, ?, ?, ?)",
                    (clean_title, clean_url, clean_cat, clean_note, now_str),
                )
                new_id = cur.lastrowid
                conn.commit()
            finally:
                conn.close()
            self._sync_to_library()

        return {
            "id": new_id,
            "title": clean_title,
            "url": clean_url,
            "category": clean_cat,
            "note": clean_note,
            "created_at": now_str,
        }

    def delete_bookmark(self, bm_id: int) -> bool:
        db_file = self._ensure_db()
        with self._lock:
            conn = sqlite3.connect(db_file)
            try:
                cur = conn.execute("DELETE FROM bookmarks WHERE id = ?", (bm_id,))
                deleted = cur.rowcount > 0
                conn.commit()
            finally:
                conn.close()
            if deleted:
                self._sync_to_library()
        return deleted

    def add_note(
        self,
        title: str,
        content: str,
        author: str = "Kullanıcı",
        category: str = "Genel",
        pinned: bool = False,
    ) -> Dict[str, Any]:
        db_file = self._ensure_db()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        clean_title = (title or "Başlıksız Not").strip()
        clean_author = (author or "Kullanıcı").strip()
        clean_cat = (category or "Genel").strip()
        clean_content = (content or "").strip()

        with self._lock:
            conn = sqlite3.connect(db_file)
            try:
                cur = conn.execute(
                    "INSERT INTO notes (title, author, category, content, pinned, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (clean_title, clean_author, clean_cat, clean_content, 1 if pinned else 0, now_str),
                )
                new_id = cur.lastrowid
                conn.commit()
            finally:
                conn.close()
            self._sync_to_library()

        return {
            "id": new_id,
            "title": clean_title,
            "author": clean_author,
            "category": clean_cat,
            "content": clean_content,
            "pinned": bool(pinned),
            "created_at": now_str,
        }

    def toggle_pin_note(self, note_id: int) -> bool:
        db_file = self._ensure_db()
        with self._lock:
            conn = sqlite3.connect(db_file)
            try:
                conn.execute(
                    "UPDATE notes SET pinned = CASE WHEN pinned = 1 THEN 0 ELSE 1 END WHERE id = ?",
                    (note_id,),
                )
                conn.commit()
            finally:
                conn.close()
            self._sync_to_library()
        return True

    def delete_note(self, note_id: int) -> bool:
        db_file = self._ensure_db()
        with self._lock:
            conn = sqlite3.connect(db_file)
            try:
                cur = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
                deleted = cur.rowcount > 0
                conn.commit()
            finally:
                conn.close()
            if deleted:
                self._sync_to_library()
        return deleted


class PersonalDocsManager:
    ALLOWED_EXTS = {".txt", ".md", ".pdf", ".html", ".htm", ".csv", ".json", ".epub"}
    TEXT_EXTS = {".txt", ".md", ".html", ".htm", ".csv", ".json"}

    def __init__(self, docs_dir: Path):
        self.docs_dir = docs_dir
        self.meta_file = self.docs_dir / "_metadata.json"
        self._lock = threading.Lock()
        self._seeded = False

    def _ensure_seeded(self) -> None:
        if self._seeded:
            return
        with self._lock:
            if self._seeded:
                return
            self.docs_dir.mkdir(parents=True, exist_ok=True)
            meta = self._read_meta_unlocked()
            changed = False
            for starter in STARTER_DOCS:
                fpath = self.docs_dir / starter["filename"]
                if not fpath.exists() and starter["filename"] not in meta:
                    fpath.write_text(starter["content"], encoding="utf-8")
                    meta[starter["filename"]] = {
                        "title": starter["title"],
                        "category": starter["category"],
                        "description": starter["description"],
                        "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    }
                    changed = True
            if changed:
                self._write_meta_unlocked(meta)
            self._seeded = True

    def _read_meta_unlocked(self) -> Dict[str, Dict[str, Any]]:
        if not self.meta_file.exists():
            return {}
        try:
            return json.loads(self.meta_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_meta_unlocked(self, meta: Dict[str, Dict[str, Any]]) -> None:
        try:
            self.meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Belge üstverisi yazılamadı: %s", exc)

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        name = Path(filename).name
        stem = re.sub(r"[^a-zA-Z0-9_\-ğüşıöçĞÜŞİÖÇ.]", "_", Path(name).stem)
        ext = Path(name).suffix.lower()
        if not ext:
            ext = ".txt"
        return f"{stem[:80]}{ext}"

    def list_docs(self, q: str = "", category: str = "all") -> Dict[str, Any]:
        self._ensure_seeded()
        query = (q or "").strip().lower()
        cat = (category or "all").strip()

        with self._lock:
            meta = self._read_meta_unlocked()

        items = []
        total_bytes = 0
        if self.docs_dir.exists():
            for f in sorted(self.docs_dir.iterdir(), key=lambda p: p.name.lower()):
                if not f.is_file() or f.name.startswith("_"):
                    continue
                ext = f.suffix.lower()
                if ext not in self.ALLOWED_EXTS:
                    continue
                stat = f.stat()
                total_bytes += stat.st_size
                info = meta.get(f.name, {})
                title = info.get("title") or f.stem.replace("_", " ")
                doc_cat = info.get("category") or "Genel"
                desc = info.get("description") or f"{ext.upper()[1:]} Belgesi"
                uploaded_at = info.get("uploaded_at") or datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")

                if cat != "all" and doc_cat != cat:
                    continue
                if query and query not in title.lower() and query not in f.name.lower() and query not in desc.lower():
                    continue

                items.append({
                    "filename": f.name,
                    "title": title,
                    "category": doc_cat,
                    "description": desc,
                    "ext": ext,
                    "is_text": ext in self.TEXT_EXTS,
                    "size_bytes": stat.st_size,
                    "size_human": format_bytes(stat.st_size),
                    "uploaded_at": uploaded_at,
                })

        return {
            "items": items,
            "count": len(items),
            "total_bytes": total_bytes,
            "total_human": format_bytes(total_bytes),
        }

    def save_doc(
        self,
        filename: str,
        content_bytes: bytes,
        title: str = "",
        category: str = "Genel",
        description: str = "",
    ) -> Dict[str, Any]:
        self._ensure_seeded()
        safe_name = self.sanitize_filename(filename)
        ext = Path(safe_name).suffix.lower()
        if ext not in self.ALLOWED_EXTS:
            raise ValueError(f"Desteklenmeyen dosya uzantısı: {ext}. İzin verilenler: {', '.join(sorted(self.ALLOWED_EXTS))}")

        dest = self.docs_dir / safe_name
        dest.write_bytes(content_bytes)

        with self._lock:
            meta = self._read_meta_unlocked()
            meta[safe_name] = {
                "title": (title or Path(safe_name).stem.replace("_", " ")).strip(),
                "category": (category or "Genel").strip(),
                "description": (description or "").strip(),
                "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            self._write_meta_unlocked(meta)

        return {
            "filename": safe_name,
            "size_bytes": len(content_bytes),
            "size_human": format_bytes(len(content_bytes)),
            **meta[safe_name],
        }

    def read_text_doc(self, filename: str) -> Dict[str, Any]:
        self._ensure_seeded()
        safe_name = Path(filename).name
        if not safe_name or safe_name in (".", ".."):
            raise FileNotFoundError("Geçersiz dosya adı.")
        target = (self.docs_dir / safe_name).resolve()
        try:
            if not target.is_relative_to(self.docs_dir.resolve()):
                raise FileNotFoundError("Yetkisiz erişim.")
        except AttributeError:
            if not str(target).startswith(str(self.docs_dir.resolve())):
                raise FileNotFoundError("Yetkisiz erişim.")
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"{safe_name} bulunamadı.")

        ext = target.suffix.lower()
        if ext not in self.TEXT_EXTS:
            return {
                "filename": safe_name,
                "ext": ext,
                "is_text": False,
                "content": "",
                "download_url": f"/api/docs/raw/{safe_name}",
            }

        raw_bytes = target.read_bytes()
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = raw_bytes.decode("latin-1", errors="replace")

        with self._lock:
            meta = self._read_meta_unlocked().get(safe_name, {})

        return {
            "filename": safe_name,
            "title": meta.get("title") or target.stem.replace("_", " "),
            "category": meta.get("category") or "Genel",
            "description": meta.get("description") or "",
            "ext": ext,
            "is_text": True,
            "size_human": format_bytes(len(raw_bytes)),
            "content": text,
        }

    def get_file_path(self, filename: str) -> Path:
        self._ensure_seeded()
        safe_name = Path(filename).name
        if not safe_name or safe_name in (".", ".."):
            raise FileNotFoundError("Geçersiz dosya adı.")
        target = (self.docs_dir / safe_name).resolve()
        try:
            if not target.is_relative_to(self.docs_dir.resolve()):
                raise FileNotFoundError("Yetkisiz erişim.")
        except AttributeError:
            if not str(target).startswith(str(self.docs_dir.resolve())):
                raise FileNotFoundError("Yetkisiz erişim.")
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"{safe_name} bulunamadı.")
        return target

    def delete_doc(self, filename: str) -> bool:
        self._ensure_seeded()
        safe_name = Path(filename).name
        if not safe_name or safe_name in (".", ".."):
            return False
        target = (self.docs_dir / safe_name).resolve()
        try:
            if not target.is_relative_to(self.docs_dir.resolve()):
                return False
        except AttributeError:
            if not str(target).startswith(str(self.docs_dir.resolve())):
                return False
        deleted = False
        if target.exists() and target.is_file():
            target.unlink()
            deleted = True
        with self._lock:
            meta = self._read_meta_unlocked()
            if safe_name in meta:
                meta.pop(safe_name, None)
                self._write_meta_unlocked(meta)
        return deleted


REPO_ROOT = Path(__file__).resolve().parent.parent
CONF_PATH = Path(os.environ.get("PREPPER_CONF_PATH", str(REPO_ROOT / "config" / "content.conf")))
LIBRARY_DIR = Path(os.environ.get("PREPPER_LIBRARY_DIR", str(REPO_ROOT / "library")))
ZIM_DIR = Path(os.environ.get("PREPPER_ZIM_DIR", str(LIBRARY_DIR / "zims" / "content")))
LIBRARY_XML = Path(os.environ.get("PREPPER_LIBRARY_XML", str(LIBRARY_DIR / "zims" / "library.xml")))
MODELS_DIR = Path(os.environ.get("PREPPER_MODELS_DIR", str(LIBRARY_DIR / "models" / "argos")))
DICT_DIR = Path(os.environ.get("PREPPER_DICT_DIR", str(LIBRARY_DIR / "dictionaries")))
NOTES_DIR = Path(os.environ.get("PREPPER_NOTES_DIR", str(LIBRARY_DIR / "notes")))
DOCS_DIR = Path(os.environ.get("PREPPER_DOCS_DIR", str(LIBRARY_DIR / "docs")))
MAPS_DIR = Path(os.environ.get("PREPPER_MAPS_DIR", str(LIBRARY_DIR / "maps")))
KIWIX_PORT = int(os.environ.get("KIWIX_PORT", "8081"))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "prepper").strip()

# Captive Portal Etkinlik Durumu (Varsayılan Açık)
CAPTIVE_PORTAL_ENABLED = os.environ.get("CAPTIVE_PORTAL_ENABLED", "true").lower() in ("true", "1", "yes")

WWW_HOME = REPO_ROOT / "www" / "home" / "index.html"
WWW_SETUP = REPO_ROOT / "www" / "setup" / "index.html"
WWW_TRANSLATE = REPO_ROOT / "www" / "translate" / "index.html"
WWW_DICTIONARY = REPO_ROOT / "www" / "dictionary" / "index.html"
WWW_TOOLS = REPO_ROOT / "www" / "tools" / "index.html"
WWW_DOCS = REPO_ROOT / "www" / "docs" / "index.html"
WWW_MAPS = REPO_ROOT / "www" / "maps" / "index.html"
WWW_MAPS_DIR = REPO_ROOT / "www" / "maps"

kiwix_manager = KiwixManager(zim_dir=ZIM_DIR, library_xml=LIBRARY_XML, port=KIWIX_PORT)
download_manager = DownloadManager(
    zim_dir=ZIM_DIR,
    on_package_complete=kiwix_manager.rebuild_library_and_reload,
    max_concurrent=3,
)
local_translator = LocalTranslator(models_dir=MODELS_DIR)
dictionary_manager = DictionaryManager(dict_dir=DICT_DIR, zim_dir=ZIM_DIR)
notes_manager = NotesAndBookmarksManager(notes_dir=NOTES_DIR)
docs_manager = PersonalDocsManager(docs_dir=DOCS_DIR)

# -------------------------------------------------------------------------
# Çevrimdışı Harita Yöneticisi (Protomaps PMTiles / OpenStreetMap)
# -------------------------------------------------------------------------

class OfflineMapManager:
    def __init__(self, maps_dir: Path, www_maps_dir: Path):
        self.maps_dir = maps_dir
        self.www_maps_dir = www_maps_dir
        self.download_state: Dict[str, Any] = {"status": "idle", "percent": 0, "message": ""}
        self._lock = asyncio.Lock()

    def get_status(self) -> Dict[str, Any]:
        meta_file = self.maps_dir / "map.json"
        pmtiles_file = self.maps_dir / "turkiye.pmtiles"
        installed = pmtiles_file.exists() and pmtiles_file.stat().st_size > 1024 * 1024
        meta = {}
        if installed and meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "installed": installed,
            "size_bytes": pmtiles_file.stat().st_size if installed else 0,
            "size_human": format_bytes(pmtiles_file.stat().st_size) if installed else "—",
            "name": meta.get("name", "turkiye"),
            "build": meta.get("build", "—"),
            "download_state": self.download_state
        }

    async def start_extract(self, map_name: str = "turkiye", max_zoom: int = 15):
        async with self._lock:
            if self.download_state.get("status") == "downloading":
                return self.download_state
            self.download_state = {
                "status": "downloading",
                "percent": 5,
                "message": "En güncel OpenStreetMap planet sürümü taranıyor..."
            }
        asyncio.create_task(self._do_extract(map_name, max_zoom))
        return self.download_state

    async def _do_extract(self, map_name: str, max_zoom: int):
        self.maps_dir.mkdir(parents=True, exist_ok=True)
        out_file = self.maps_dir / f"{map_name}.pmtiles"
        part_file = self.maps_dir / f"{map_name}.pmtiles.part"
        meta_file = self.maps_dir / "map.json"

        try:
            # 1. En güncel planet build bul
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get("https://build-metadata.protomaps.dev/builds.json")
                builds = r.json()
                keys = [b["key"] for b in builds if "key" in b and b["key"].endswith(".pmtiles")]
                latest_build = sorted(keys)[-1].replace(".pmtiles", "")

            src_url = f"https://build.protomaps.com/{latest_build}.pmtiles"
            bbox = "25.5,35.7,45.0,42.2"  # Türkiye ve kıyı payı

            self.download_state.update({
                "percent": 15,
                "message": f"Türkiye kesiti (z{max_zoom}) çıkarılıyor (Build {latest_build})..."
            })

            # pmtiles CLI çağrısı
            cmd = [
                "pmtiles", "extract", src_url, str(part_file),
                f"--bbox={bbox}", f"--maxzoom={max_zoom}", "--download-threads=4"
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0 and part_file.exists() and part_file.stat().st_size > 1024 * 1024:
                part_file.replace(out_file)
                bytes_size = out_file.stat().st_size
                meta = {
                    "name": map_name,
                    "build": latest_build,
                    "bbox": [25.5, 35.7, 45.0, 42.2],
                    "maxzoom": max_zoom,
                    "bytes": bytes_size,
                    "updated": datetime.now().isoformat(),
                    "source": src_url
                }
                meta_file.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
                self.download_state = {
                    "status": "completed",
                    "percent": 100,
                    "message": f"Harita başarıyla kuruldu ({format_bytes(bytes_size)})"
                }
            else:
                part_file.unlink(missing_ok=True)
                err_msg = stderr.decode(errors="replace")[:200]
                self.download_state = {
                    "status": "error",
                    "percent": 0,
                    "message": f"Harita kesiti başarısız oldu: {err_msg}"
                }
        except Exception as exc:
            part_file.unlink(missing_ok=True)
            self.download_state = {
                "status": "error",
                "percent": 0,
                "message": f"Hata: {exc}"
            }

    async def delete_map(self):
        async with self._lock:
            for f in self.maps_dir.glob("*.pmtiles*"):
                try: f.unlink()
                except OSError: pass
            meta_file = self.maps_dir / "map.json"
            if meta_file.exists():
                meta_file.unlink(missing_ok=True)
            self.download_state = {"status": "idle", "percent": 0, "message": "Harita silindi."}

map_manager = OfflineMapManager(maps_dir=MAPS_DIR, www_maps_dir=WWW_MAPS_DIR)



def _startup_warmup() -> None:
    try:
        local_translator.get_status()
        dictionary_manager.get_status()
        notes_manager.get_all()
        docs_manager.list_docs()
        kiwix_manager.rebuild_library_and_reload()
    except Exception as exc:
        logger.error("Başlangıç önbellek hazırlama hatası: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    for d in (ZIM_DIR, LIBRARY_XML.parent, MODELS_DIR, DICT_DIR, NOTES_DIR, DOCS_DIR, MAPS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    asyncio.create_task(asyncio.to_thread(_startup_warmup))
    yield
    kiwix_manager.stop()


app = FastAPI(
    title="HAS_PrepperDisk Web & Docker Manager",
    version="2.5.0",
    lifespan=lifespan,
    docs_url="/api/swagger",
    redoc_url=None,
)


class StartDownloadRequest(BaseModel):
    prefixes: List[str]
    save_to_conf: bool = True
    max_concurrent: Optional[int] = None


class CustomZimUrlRequest(BaseModel):
    url: str
    name: Optional[str] = None


class SetConcurrencyRequest(BaseModel):
    max_concurrent: int


class CancelDownloadRequest(BaseModel):
    prefix: Optional[str] = None
    delete_partial: bool = False


class BulkDeleteRequest(BaseModel):
    prefixes: List[str]


class TranslateRequest(BaseModel):
    text: str
    from_code: str = "en"
    to_code: str = "tr"


class DownloadModelRequest(BaseModel):
    packs: Optional[List[str]] = None
    langs: Optional[List[str]] = None


class DownloadDictRequest(BaseModel):
    packs: List[str]


class AddBookmarkRequest(BaseModel):
    title: str
    url: str
    category: str = "Genel"
    note: str = ""


class AddNoteRequest(BaseModel):
    title: str
    content: str
    author: str = "Kullanıcı"
    category: str = "Genel"
    pinned: bool = False


class UploadDocJsonRequest(BaseModel):
    filename: str
    title: str = ""
    category: str = "Genel"
    description: str = ""
    content_base64: Optional[str] = None
    content_text: Optional[str] = None


def get_disk_stats() -> dict:
    target = ZIM_DIR if ZIM_DIR.exists() else REPO_ROOT
    usage = shutil.disk_usage(target)
    used_pct = round((usage.used / usage.total) * 100, 1) if usage.total > 0 else 0.0
    return {
        "path": str(LIBRARY_DIR),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "total_human": format_bytes(usage.total),
        "used_human": format_bytes(usage.used),
        "free_human": format_bytes(usage.free),
        "used_percent": used_pct,
    }


# -------------------------------------------------------------------------
# Sayfa Yönlendirmeleri (/ , /home , /setup , /translate , /dictionary , /tools , /docs)
# -------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def root_redirect():
    installed = scan_installed_zims(ZIM_DIR)
    if not installed:
        return RedirectResponse(url="/setup")
    return RedirectResponse(url="/home")


@app.get("/home", include_in_schema=False)
@app.get("/home/", include_in_schema=False)
@app.get("/home/index.html", include_in_schema=False)
async def serve_home():
    if not WWW_HOME.exists():
        raise HTTPException(status_code=404, detail="www/home/index.html bulunamadı")
    return FileResponse(WWW_HOME, media_type="text/html; charset=utf-8")


@app.get("/setup", include_in_schema=False)
@app.get("/setup/", include_in_schema=False)
@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
async def serve_setup():
    if not WWW_SETUP.exists():
        raise HTTPException(status_code=404, detail="www/setup/index.html bulunamadı")
    return FileResponse(WWW_SETUP, media_type="text/html; charset=utf-8")


@app.get("/translate", include_in_schema=False)
@app.get("/translate/", include_in_schema=False)
@app.get("/translate/index.html", include_in_schema=False)
async def serve_translate():
    if not WWW_TRANSLATE.exists():
        raise HTTPException(status_code=404, detail="www/translate/index.html bulunamadı")
    return FileResponse(WWW_TRANSLATE, media_type="text/html; charset=utf-8")


@app.get("/dictionary", include_in_schema=False)
@app.get("/dictionary/", include_in_schema=False)
@app.get("/dictionary/index.html", include_in_schema=False)
async def serve_dictionary():
    if not WWW_DICTIONARY.exists():
        raise HTTPException(status_code=404, detail="www/dictionary/index.html bulunamadı")
    return FileResponse(WWW_DICTIONARY, media_type="text/html; charset=utf-8")


@app.get("/tools", include_in_schema=False)
@app.get("/tools/", include_in_schema=False)
@app.get("/tools/index.html", include_in_schema=False)
@app.get("/notes", include_in_schema=False)
@app.get("/notes/", include_in_schema=False)
@app.get("/notes/index.html", include_in_schema=False)
async def serve_tools():
    if not WWW_TOOLS.exists():
        raise HTTPException(status_code=404, detail="www/tools/index.html bulunamadı")
    return FileResponse(WWW_TOOLS, media_type="text/html; charset=utf-8")


@app.get("/docs", include_in_schema=False)
@app.get("/docs/", include_in_schema=False)
@app.get("/docs/index.html", include_in_schema=False)
async def serve_docs():
    if not WWW_DOCS.exists():
        raise HTTPException(status_code=404, detail="www/docs/index.html bulunamadı")
    return FileResponse(WWW_DOCS, media_type="text/html; charset=utf-8")

# -------------------------------------------------------------------------
# Hotspot Captive Portal Rotaları (Android, Apple, Windows Wi-Fi Otomatik Karşılama)
# -------------------------------------------------------------------------

@app.get("/generate_204", include_in_schema=False)
@app.get("/gen_204", include_in_schema=False)
@app.get("/hotspot-detect.html", include_in_schema=False)
@app.get("/canonical.html", include_in_schema=False)
@app.get("/connecttest.txt", include_in_schema=False)
@app.get("/ncsi.txt", include_in_schema=False)
async def captive_portal_probe(request: Request):
    if CAPTIVE_PORTAL_ENABLED:
        # Telefonda Wi-Fi ağına bağlanan kullanıcıyı doğrudan HAS_PrepperDisk Ana Sayfasına fırlat
        return RedirectResponse(url="/home", status_code=302)
    return Response(status_code=204)


@app.get("/maps", include_in_schema=False)
@app.get("/maps/", include_in_schema=False)
@app.get("/maps/index.html", include_in_schema=False)
@app.get("/harita", include_in_schema=False)
@app.get("/harita/", include_in_schema=False)
async def serve_maps():
    if not WWW_MAPS.exists():
        raise HTTPException(status_code=404, detail="www/maps/index.html bulunamadı")
    return FileResponse(WWW_MAPS, media_type="text/html; charset=utf-8")


@app.get("/maps/lib/{filename:path}", include_in_schema=False)
@app.get("/lib/{filename:path}", include_in_schema=False)
async def serve_maps_lib(filename: str):
    base_dir = (WWW_MAPS_DIR / "lib").resolve()
    fpath = (base_dir / filename).resolve()
    try:
        if not fpath.is_relative_to(base_dir):
            raise HTTPException(status_code=403, detail="Yetkisiz erişim.")
    except AttributeError:
        if not str(fpath).startswith(str(base_dir)):
            raise HTTPException(status_code=403, detail="Yetkisiz erişim.")
    if not fpath.exists() or not fpath.is_file():
        raise HTTPException(status_code=404, detail="Harita kütüphane dosyası bulunamadı")
    media = "application/javascript" if filename.endswith(".js") else ("text/css" if filename.endswith(".css") else "application/octet-stream")
    return FileResponse(fpath, media_type=media)


@app.get("/api/maps/status")
async def api_maps_status():
    st = map_manager.get_status()
    st["captive_portal_enabled"] = CAPTIVE_PORTAL_ENABLED
    return st


@app.post("/api/maps/download")
async def api_maps_download(request: Request):
    verify_admin_auth(request)
    return await map_manager.start_extract(map_name="turkiye", max_zoom=15)


@app.delete("/api/maps")
async def api_maps_delete(request: Request):
    verify_admin_auth(request)
    await map_manager.delete_map()
    return {"ok": True, "message": "Harita dosyaları diskten silindi."}


@app.post("/api/captive/toggle")
async def api_captive_toggle(request: Request):
    verify_admin_auth(request)
    global CAPTIVE_PORTAL_ENABLED
    try:
        body = await request.json()
    except Exception:
        body = {}
    enabled = body.get("enabled")
    if enabled is None:
        CAPTIVE_PORTAL_ENABLED = not CAPTIVE_PORTAL_ENABLED
    else:
        CAPTIVE_PORTAL_ENABLED = bool(enabled)
    return {"ok": True, "captive_portal_enabled": CAPTIVE_PORTAL_ENABLED}


@app.get("/api/maps/data/{filepath:path}")
async def serve_maps_data(filepath: str, request: Request):
    # PMTiles, map.json ve assets (fonts/sprites) için Range destekli servis
    # Önce /library/maps içinde ara (indirilmiş harita ve meta), yoksa www/maps/data içinde ara (fonts/sprites)
    maps_base = MAPS_DIR.resolve()
    assets_base = (WWW_MAPS_DIR / "data").resolve()

    target_maps = (maps_base / filepath).resolve()
    target_assets = (assets_base / filepath).resolve()

    fpath = None
    try:
        if target_maps.is_relative_to(maps_base) and target_maps.exists() and target_maps.is_file():
            fpath = target_maps
        elif target_assets.is_relative_to(assets_base) and target_assets.exists() and target_assets.is_file():
            fpath = target_assets
    except AttributeError:
        if str(target_maps).startswith(str(maps_base)) and target_maps.exists() and target_maps.is_file():
            fpath = target_maps
        elif str(target_assets).startswith(str(assets_base)) and target_assets.exists() and target_assets.is_file():
            fpath = target_assets

    if not fpath:
        raise HTTPException(status_code=404, detail="Harita verisi bulunamadı")

    if filepath.endswith(".json"):
        return FileResponse(fpath, media_type="application/json")
    elif filepath.endswith(".pbf"):
        return FileResponse(fpath, media_type="application/x-protobuf")
    elif filepath.endswith(".png"):
        return FileResponse(fpath, media_type="image/png")

    # .pmtiles için Range destekli FileResponse
    return FileResponse(fpath, media_type="application/octet-stream")



# -------------------------------------------------------------------------
# REST API Uç Noktaları (/api/*)
# -------------------------------------------------------------------------

@app.get("/api/status")
async def api_status():
    installed = scan_installed_zims(ZIM_DIR)
    partials = scan_partial_zims(ZIM_DIR)
    dl_status = download_manager.get_status()
    return {
        "setup_completed": len(installed) > 0,
        "installed_count": len(installed),
        "partial_count": len(partials),
        "kiwix_running": kiwix_manager.is_running(),
        "has_kiwix_binaries": kiwix_manager.has_kiwix_binaries,
        "disk": get_disk_stats(),
        "downloads": dl_status,
        "translator": local_translator.get_status(),
        "dictionary": dictionary_manager.get_status(),
    }


@app.get("/api/catalog")
async def api_catalog():
    conf_items = parse_content_conf(CONF_PATH)
    installed = scan_installed_zims(ZIM_DIR)
    partials = scan_partial_zims(ZIM_DIR)
    dl_status = download_manager.get_status()

    active_prefixes = {a["prefix"] for a in dl_status.get("active_downloads", [])}
    queued_prefixes = {q["prefix"] for q in dl_status["queue"]}

    seen_prefixes = set()
    enriched_items = []

    for item in conf_items:
        prefix = item["prefix"]
        seen_prefixes.add(prefix)

        inst = installed.get(prefix)
        part = partials.get(prefix)

        if prefix in active_prefixes:
            status = "downloading"
        elif prefix in queued_prefixes:
            status = "queued"
        elif inst:
            status = "installed"
        elif part:
            status = "partial"
        else:
            status = "not_installed"

        enriched_items.append({
            **item,
            "status": status,
            "installed_file": inst["filename"] if inst else None,
            "version": inst["version"] if inst else None,
            "installed_bytes": inst["size_bytes"] if inst else 0,
            "installed_human": format_bytes(inst["size_bytes"]) if inst else None,
            "href": inst["href"] if inst else None,
            "partial_bytes": part["downloaded_bytes"] if part else 0,
            "partial_human": format_bytes(part["downloaded_bytes"]) if part else None,
        })

    for prefix, inst in installed.items():
        if prefix not in seen_prefixes:
            meta = KNOWN_METADATA.get(prefix, {})
            enriched_items.append({
                "id": prefix,
                "prefix": prefix,
                "folder": "other",
                "name": meta.get("name", prefix),
                "desc": meta.get("desc", f"Yerel ZIM dosyası ({inst['filename']})"),
                "lang": meta.get("lang", "—"),
                "size": format_bytes(inst["size_bytes"]),
                "size_bytes": inst["size_bytes"],
                "category": meta.get("category", "Diğer Kaynaklar"),
                "search": meta.get("search", True),
                "enabled_in_conf": True,
                "status": "installed",
                "installed_file": inst["filename"],
                "version": inst["version"],
                "installed_bytes": inst["size_bytes"],
                "installed_human": format_bytes(inst["size_bytes"]),
                "href": inst["href"],
                "partial_bytes": 0,
                "partial_human": None,
            })

    return {
        "items": enriched_items,
        "disk": get_disk_stats(),
        "downloads": dl_status,
        "translator": local_translator.get_status(),
        "dictionary": dictionary_manager.get_status(),
    }


@app.post("/api/downloads/start")
async def api_start_downloads(req: StartDownloadRequest):
    conf_items = parse_content_conf(CONF_PATH)
    by_prefix = {item["prefix"]: item for item in conf_items}

    to_enqueue = []
    for prefix in req.prefixes:
        if prefix in by_prefix:
            to_enqueue.append({
                "prefix": prefix,
                "folder": by_prefix[prefix]["folder"],
                "name": by_prefix[prefix]["name"],
            })

    if not to_enqueue:
        raise HTTPException(status_code=400, detail="Geçerli bir paket seçilmedi.")

    if req.save_to_conf:
        installed = scan_installed_zims(ZIM_DIR)
        active_set = set(req.prefixes) | set(installed.keys())
        update_content_conf(CONF_PATH, active_set)

    res = await download_manager.enqueue(to_enqueue, max_concurrent=req.max_concurrent)
    return {"ok": True, **res, "downloads": download_manager.get_status()}


@app.post("/api/downloads/custom-url")
async def api_download_custom_url(req: CustomZimUrlRequest):
    url = (req.url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Geçerli bir http:// veya https:// ZIM adresi girin.")
    parsed = urlparse(url)
    raw_name = Path(parsed.path).name
    if not raw_name.endswith(".zim"):
        raw_name = f"{raw_name or 'custom_archive'}_2026-01.zim"
    safe_name = re.sub(r"[^a-zA-Z0-9_.\-]", "_", raw_name)
    m = re.match(r"^(.*?)_\d{4}-\d{2}[a-z]?\.zim$", safe_name)
    prefix = m.group(1) if m else safe_name[:-4]
    display_name = (req.name or prefix).strip()

    res = await download_manager.enqueue([{
        "prefix": prefix,
        "folder": "custom",
        "name": display_name,
        "custom_url": url,
        "custom_filename": safe_name,
    }])
    return {"ok": True, "filename": safe_name, "prefix": prefix, **res, "downloads": download_manager.get_status()}


@app.post("/api/packages/upload-zim")
async def api_upload_local_zim(request: Request, filename: str = ""):
    raw_name = (filename or request.headers.get("x-filename") or "uploaded_archive_2026-01.zim").strip()
    if not raw_name.lower().endswith(".zim"):
        raise HTTPException(status_code=400, detail="Sadece .zim uzantılı arşiv dosyaları yüklenebilir.")
    safe_name = re.sub(r"[^a-zA-Z0-9_.\-]", "_", Path(raw_name).name)
    ZIM_DIR.mkdir(parents=True, exist_ok=True)
    dest_path = ZIM_DIR / safe_name
    part_path = ZIM_DIR / f"{safe_name}.part"

    total_written = 0
    with open(part_path, "wb") as f:
        async for chunk in request.stream():
            if chunk:
                await asyncio.to_thread(f.write, chunk)
                total_written += len(chunk)

    if total_written == 0:
        part_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Boş dosya yüklendi.")

    part_path.replace(dest_path)
    invalidate_zim_scan_cache()
    await asyncio.to_thread(kiwix_manager.rebuild_library_and_reload)
    return {
        "ok": True,
        "filename": safe_name,
        "size_bytes": total_written,
        "size_human": format_bytes(total_written),
    }


@app.post("/api/downloads/concurrency")
async def api_set_concurrency(req: SetConcurrencyRequest):
    dl_status = await download_manager.set_concurrency(req.max_concurrent)
    return {"ok": True, "downloads": dl_status}


@app.get("/api/downloads/progress")
async def api_downloads_progress():
    return download_manager.get_status()


@app.post("/api/downloads/cancel")
async def api_cancel_download(req: CancelDownloadRequest):
    res = await download_manager.cancel(prefix=req.prefix, delete_partial=req.delete_partial)
    return {"ok": True, **res, "downloads": download_manager.get_status()}


def verify_admin_auth(request: Request) -> None:
    if not ADMIN_PASSWORD:
        return
    auth_header = request.headers.get("x-admin-password") or request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    else:
        token = auth_header.strip()

    # Query param alternatifi: ?admin_password=...
    if not token:
        token = request.query_params.get("admin_password", "").strip()

    if token != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Yönetici şifresi geçersiz veya eksik.")


def is_valid_catalog_prefix(prefix: str) -> bool:
    if not prefix or not re.match(r"^[a-zA-Z0-9_\-.]+$", prefix):
        return False
    # Bilinen katalog veya özel zim öneki kontrolü
    if prefix in KNOWN_METADATA:
        return True
    conf_items = parse_content_conf(CONF_PATH)
    if any(i.get("prefix") == prefix for i in conf_items):
        return True
    # /library/zims/content içinde var olan bir dosya mı kontrolü
    matching = list(ZIM_DIR.glob(f"{prefix}_*.zim")) + list(ZIM_DIR.glob(f"{prefix}.zim")) + list(ZIM_DIR.glob(f"{prefix}_*.zim.part"))
    return len(matching) > 0


@app.delete("/api/packages/{prefix}")
async def api_delete_package(prefix: str, request: Request):
    verify_admin_auth(request)

    clean_prefix = re.sub(r"[^a-zA-Z0-9_\-.]", "", prefix).strip()
    if not clean_prefix or clean_prefix in (".", "..") or not is_valid_catalog_prefix(clean_prefix):
        raise HTTPException(status_code=400, detail="Geçersiz veya yetkisiz paket adı.")
    prefix = clean_prefix

    await download_manager.cancel(prefix=prefix, delete_partial=True)

    deleted_files = []
    if ZIM_DIR.exists():
        for f in list(ZIM_DIR.glob(f"{prefix}_*.zim")) + list(ZIM_DIR.glob(f"{prefix}.zim")) + list(ZIM_DIR.glob(f"{prefix}_*.zim.part")):
            if f.is_file():
                try:
                    f.unlink()
                    deleted_files.append(f.name)
                except OSError as exc:
                    raise HTTPException(status_code=500, detail=f"{f.name} silinemedi: {exc}")

    kiwix_manager.rebuild_library_and_reload()
    return {"ok": True, "deleted": deleted_files}


@app.post("/api/packages/bulk-delete")
async def api_bulk_delete_packages(req: BulkDeleteRequest, request: Request):
    verify_admin_auth(request)

    if not req.prefixes:
        raise HTTPException(status_code=400, detail="Silinecek paket seçilmedi.")

    deleted_files = []
    for raw_prefix in req.prefixes:
        prefix = re.sub(r"[^a-zA-Z0-9_\-.]", "", raw_prefix).strip()
        if not prefix or prefix in (".", "..") or not is_valid_catalog_prefix(prefix):
            continue
        await download_manager.cancel(prefix=prefix, delete_partial=True)
        if ZIM_DIR.exists():
            for f in (
                list(ZIM_DIR.glob(f"{prefix}_*.zim"))
                + list(ZIM_DIR.glob(f"{prefix}.zim"))
                + list(ZIM_DIR.glob(f"{prefix}_*.zim.part"))
            ):
                if f.is_file():
                    try:
                        f.unlink()
                        deleted_files.append(f.name)
                    except OSError as exc:
                        logger.error("%s silinemedi: %s", f.name, exc)

    kiwix_manager.rebuild_library_and_reload()
    return {"ok": True, "deleted": deleted_files, "deleted_count": len(deleted_files)}


@app.post("/api/kiwix/reload")
async def api_reload_kiwix():
    running = kiwix_manager.rebuild_library_and_reload()
    return {"ok": True, "kiwix_running": running}


# -------------------------------------------------------------------------
# Yerel Çevrimdışı Çeviri API Uç Noktaları (/api/translate/*)
# -------------------------------------------------------------------------

@app.get("/api/translate/status")
async def api_translate_status():
    return local_translator.get_status()


@app.post("/api/translate/models/download")
async def api_translate_download_models(req: DownloadModelRequest):
    res = await local_translator.download_packs(pack_ids=req.packs, lang_codes=req.langs)
    return {"ok": True, **res}


@app.delete("/api/translate/models/{lang_or_pack}")
async def api_translate_delete_model(lang_or_pack: str):
    res = await local_translator.delete_language(lang_or_pack)
    return {"ok": True, **res}


@app.post("/api/translate")
async def api_translate_text(req: TranslateRequest):
    try:
        res = await asyncio.to_thread(
            local_translator.translate_text,
            req.text,
            req.from_code,
            req.to_code,
        )
        return {"ok": True, **res}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Çeviri hatası: %s", exc)
        raise HTTPException(status_code=500, detail=f"Çeviri hatası: {exc}")


# -------------------------------------------------------------------------
# Çevrimdışı Sözlük Sistemi API Uç Noktaları (/api/dictionary/*)
# -------------------------------------------------------------------------

@app.get("/api/dictionary/status")
async def api_dictionary_status():
    return dictionary_manager.get_status()


@app.post("/api/dictionary/packs/download")
async def api_dictionary_download(req: DownloadDictRequest):
    if not req.packs:
        raise HTTPException(status_code=400, detail="İndirilecek sözlük paketi seçilmedi.")
    res = await dictionary_manager.download_packs(req.packs)
    return {"ok": True, **res}


@app.delete("/api/dictionary/packs/{pack_id}")
async def api_dictionary_delete(pack_id: str):
    res = await dictionary_manager.delete_pack(pack_id)
    return {"ok": True, **res}


@app.get("/api/dictionary/search")
async def api_dictionary_search(
    q: str = "",
    pack_id: str = "all",
    direction: str = "all",
    limit: int = 80,
):
    res = await asyncio.to_thread(
        dictionary_manager.search_entries,
        q,
        pack_id,
        direction,
        min(max(limit, 1), 250),
    )
    return {"ok": True, **res}


# -------------------------------------------------------------------------
# Ortak Saha Notları ve Yer İmleri API Uç Noktaları (/api/notes/*)
# -------------------------------------------------------------------------

@app.get("/api/notes")
async def api_get_notes(q: str = "", category: str = "all"):
    res = await asyncio.to_thread(notes_manager.get_all, q, category)
    return {"ok": True, **res}


@app.post("/api/notes/bookmarks")
async def api_add_bookmark(req: AddBookmarkRequest):
    item = await asyncio.to_thread(
        notes_manager.add_bookmark, req.title, req.url, req.category, req.note
    )
    return {"ok": True, "item": item}


@app.delete("/api/notes/bookmarks/{bm_id}")
async def api_delete_bookmark(bm_id: int):
    deleted = await asyncio.to_thread(notes_manager.delete_bookmark, bm_id)
    return {"ok": True, "deleted": deleted}


@app.post("/api/notes/items")
async def api_add_note(req: AddNoteRequest):
    item = await asyncio.to_thread(
        notes_manager.add_note, req.title, req.content, req.author, req.category, req.pinned
    )
    return {"ok": True, "item": item}


@app.post("/api/notes/items/{note_id}/pin")
async def api_pin_note(note_id: int):
    await asyncio.to_thread(notes_manager.toggle_pin_note, note_id)
    return {"ok": True}


@app.delete("/api/notes/items/{note_id}")
async def api_delete_note(note_id: int):
    deleted = await asyncio.to_thread(notes_manager.delete_note, note_id)
    return {"ok": True, "deleted": deleted}


# -------------------------------------------------------------------------
# Kişisel Belge Kitaplığı API Uç Noktaları (/api/docs/*)
# -------------------------------------------------------------------------

@app.get("/api/docs")
async def api_list_docs(q: str = "", category: str = "all"):
    res = await asyncio.to_thread(docs_manager.list_docs, q, category)
    return {"ok": True, **res}


@app.post("/api/docs/upload")
async def api_upload_doc(req: UploadDocJsonRequest):
    if req.content_base64:
        try:
            raw_bytes = base64.b64decode(req.content_base64)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Geçersiz base64 verisi: {exc}")
    elif req.content_text is not None:
        raw_bytes = req.content_text.encode("utf-8")
    else:
        raise HTTPException(status_code=400, detail="Dosya içeriği boş.")

    try:
        saved = await asyncio.to_thread(
            docs_manager.save_doc,
            req.filename,
            raw_bytes,
            req.title,
            req.category,
            req.description,
        )
        return {"ok": True, "doc": saved}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/docs/read/{filename}")
async def api_read_doc(filename: str):
    try:
        res = await asyncio.to_thread(docs_manager.read_text_doc, filename)
        return {"ok": True, **res}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/docs/raw/{filename}")
async def api_raw_doc(filename: str):
    try:
        fpath = await asyncio.to_thread(docs_manager.get_file_path, filename)
        return FileResponse(fpath)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/api/docs/{filename}")
async def api_delete_doc(filename: str):
    deleted = await asyncio.to_thread(docs_manager.delete_doc, filename)
    return {"ok": True, "deleted": deleted}


# -------------------------------------------------------------------------
# Kiwix Ters Vekil (Reverse Proxy), Makale İçi Araç Çubuğu & Katalog Emülasyonu (/kiwix/*)
# -------------------------------------------------------------------------

@app.get("/api/kiwix-helper.js", include_in_schema=False)
async def serve_kiwix_helper_js():
    return Response(content=KIWIX_HELPER_JS, media_type="application/javascript; charset=utf-8")


def build_fallback_catalog_xml() -> str:
    installed = scan_installed_zims(ZIM_DIR)
    entries = []
    for prefix, info in installed.items():
        meta = KNOWN_METADATA.get(prefix, {})
        title = xml_escape(meta.get("name", prefix))
        href = xml_escape(info["href"])
        book_id = xml_escape(info["book_id"])
        entries.append(
            f"  <entry>\n"
            f"    <id>{book_id}</id>\n"
            f"    <title>{title}</title>\n"
            f'    <link rel="alternate" type="text/html" href="{href}" />\n'
            f"  </entry>"
        )
    body = "\n".join(entries)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">\n{body}\n</feed>'


@app.api_route("/kiwix/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/kiwix", methods=["GET", "HEAD"], include_in_schema=False)
async def kiwix_proxy(request: Request, path: str = ""):
    if not kiwix_manager.is_running():
        if kiwix_manager.get_zim_files() and kiwix_manager.has_kiwix_binaries:
            kiwix_manager.rebuild_library_and_reload()

    if not kiwix_manager.is_running():
        if path.startswith("catalog/v2/entries") or path.startswith("catalog/"):
            xml_content = build_fallback_catalog_xml()
            return Response(content=xml_content, media_type="application/atom+xml; charset=utf-8")

        return HTMLResponse(
            content="""<!doctype html><html lang="tr"><head><meta charset="utf-8">
            <title>HAS_PrepperDisk :: Kütüphane Boş</title>
            <style>body{background:#E5E5E5;font-family:Verdana,sans-serif;font-size:12px;padding:30px}
            .box{max-width:520px;margin:0 auto;background:#fff;border:1px solid #006699;padding:16px}
            h2{margin:0 0 10px;color:#006699;font-size:15px}
            a.btn{display:inline-block;margin-top:10px;background:#FAFAFA;border:1px solid #000;padding:4px 10px;color:#000;text-decoration:none;font-weight:bold}
            a.btn:hover{background:#FFF3D6}</style></head>
            <body><div class="box">
            <h2>Kütüphane Henüz Hazır Değil</h2>
            <p>Cihazda henüz indirilmiş bir ZIM arşivi bulunmuyor veya Kiwix sunucusu başlatılmadı.</p>
            <a class="btn" href="/setup">» Kurulum Sihirbazını Aç (/setup)</a>
            <a class="btn" href="/home">» Ana Sayfaya Dön (/home)</a>
            </div></body></html>""",
            status_code=200,
        )

    query = request.url.query
    target_url = f"http://127.0.0.1:{KIWIX_PORT}/kiwix/{path}"
    if query:
        target_url = f"{target_url}?{query}"

    client = httpx.AsyncClient(follow_redirects=False, timeout=30.0)
    try:
        req_headers = {
            k: v for k, v in request.headers.items()
            if k.lower() not in ("host", "connection", "accept-encoding")
        }
        req_headers["accept-encoding"] = "identity"
        rp_req = client.build_request(request.method, target_url, headers=req_headers)
        rp_resp = await client.send(rp_req, stream=True)

        content_type = rp_resp.headers.get("content-type", "").lower()
        is_html = (
            request.method == "GET"
            and rp_resp.status_code == 200
            and "text/html" in content_type
            and not path.startswith("catalog/")
        )

        if is_html:
            raw_bytes = await rp_resp.aread()
            await rp_resp.aclose()
            await client.aclose()

            inject_tag = b'<script src="/api/kiwix-helper.js" defer></script>'
            lower_bytes = raw_bytes.lower()
            idx = lower_bytes.rfind(b"</body>")
            if idx != -1:
                modified = raw_bytes[:idx] + inject_tag + raw_bytes[idx:]
            else:
                modified = raw_bytes + inject_tag

            excluded_headers = {"transfer-encoding", "connection", "content-length"}
            resp_headers = {
                k: v for k, v in rp_resp.headers.items()
                if k.lower() not in excluded_headers
            }
            return Response(
                content=modified,
                status_code=rp_resp.status_code,
                headers=resp_headers,
                media_type="text/html; charset=utf-8",
            )

        excluded_headers = {"transfer-encoding", "connection"}
        resp_headers = {
            k: v for k, v in rp_resp.headers.items()
            if k.lower() not in excluded_headers
        }

        async def stream_body():
            try:
                async for chunk in rp_resp.aiter_raw():
                    yield chunk
            finally:
                await rp_resp.aclose()
                await client.aclose()

        return StreamingResponse(
            stream_body(),
            status_code=rp_resp.status_code,
            headers=resp_headers,
        )
    except Exception as exc:
        await client.aclose()
        logger.error("Kiwix proxy hatası: %s", exc)
        raise HTTPException(status_code=502, detail=f"Kiwix sunucusuna ulaşılamadı: {exc}")
