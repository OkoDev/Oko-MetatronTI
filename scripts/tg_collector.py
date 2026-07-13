# -*- coding: utf-8 -*-
"""TG-СБОРЩИК v2 — веб-превью t.me/s/ (09.07, обход my.telegram.org).

v1 (Telethon) требовал api_id с my.telegram.org — в РФ тупик: без VPN сайт закрыт,
с VPN форма отклоняет (антифрод). v2 читает ПУБЛИЧНЫЕ каналы через t.me/s/<username>
(веб-превью, без логина/API/сессий) — проверено с этой машины 09.07: работает.

Список каналов: scripts/tg_channels.txt (username на строку, # — коммент).
Посты → external_data.db tg_posts (та же таблица; врезка news_sphere уже готова:
подхватывает classified=0 в LLM-трубу → NEWS-канал).

Ограничение: только публичные каналы (у приватных нет t.me/s/). Последние ~20 постов.
pm2: pm2 start scripts/tg_collector.py --name tg-collector --interpreter <python>
Тест: python scripts/tg_collector.py --once
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
import re
import time
import html as html_mod
import urllib.request
from datetime import datetime
from pathlib import Path

from oko_feed.store import conn

CHANNELS_FILE = Path("scripts/tg_channels.txt")
CYCLE_SEC = 5 * 60
MIN_TEXT_LEN = 60
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

_MSG_RE = re.compile(
    r'data-post="(?P<post>[^"]+/(?P<mid>\d+))".*?'
    r'tgme_widget_message_text[^>]*>(?P<text>.*?)</div>.*?'
    r'<time[^>]*datetime="(?P<dt>[^"]+)"',
    re.DOTALL)


def channels() -> list[str]:
    if not CHANNELS_FILE.exists():
        return []
    out = []
    for ln in CHANNELS_FILE.read_text(encoding="utf-8").splitlines():
        ln = ln.strip().lstrip("@")
        if ln and not ln.startswith("#"):
            out.append(ln.split("/")[-1])            # терпим полные ссылки t.me/xxx
    return out


def _clean(raw: str) -> str:
    txt = re.sub(r"<br/?>", "\n", raw)
    txt = re.sub(r"<[^>]+>", "", txt)
    return html_mod.unescape(txt).strip()


def _ensure(c) -> None:
    c.execute("""CREATE TABLE IF NOT EXISTS tg_posts (
        channel_id INTEGER, msg_id INTEGER, ts INTEGER, channel TEXT, username TEXT,
        text TEXT, link TEXT, classified INTEGER DEFAULT 0,
        PRIMARY KEY (channel_id, msg_id))""")


def fetch_channel(user: str) -> list[dict]:
    req = urllib.request.Request(f"https://t.me/s/{user}", headers=UA)
    page = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")
    out = []
    for m in _MSG_RE.finditer(page):
        text = _clean(m.group("text"))
        if len(text) < MIN_TEXT_LEN:
            continue
        try:
            ts = int(datetime.fromisoformat(m.group("dt")).timestamp())
        except Exception:
            ts = int(time.time())
        out.append({"msg_id": int(m.group("mid")), "ts": ts, "text": text[:600],
                    "link": f"https://t.me/{m.group('post')}"})
    return out


def collect() -> int:
    chans = channels()
    if not chans:
        print(f"[TG] {CHANNELS_FILE} пуст — добавь каналы (username на строку)")
        return 0
    c = conn()
    added = 0
    try:
        _ensure(c)
        for user in chans:
            ch_id = hash(user) & 0x7FFFFFFF          # стабильный id из username
            try:
                last = c.execute("SELECT MAX(msg_id) FROM tg_posts WHERE channel_id=?",
                                 (ch_id,)).fetchone()[0] or 0
                for p in fetch_channel(user):
                    if p["msg_id"] <= last:
                        continue
                    c.execute("INSERT OR IGNORE INTO tg_posts VALUES (?,?,?,?,?,?,?,0)",
                              (ch_id, p["msg_id"], p["ts"], user, user, p["text"], p["link"]))
                    added += 1
            except Exception as e:
                print(f"[TG] {user}: {e}")
            time.sleep(1.0)                          # бережём t.me
        c.commit()
    finally:
        c.close()
    return added


if __name__ == "__main__":
    print(f"[TG-COLLECTOR v2] t.me/s/ превью · каналов: {len(channels())} · цикл {CYCLE_SEC//60}м")
    if "--once" in sys.argv:
        print(f"[TG-COLLECTOR] собрано: {collect()}")
        sys.exit(0)
    while True:
        try:
            n = collect()
            if n:
                print(f"[TG] {time.strftime('%H:%M')} собрано {n}")
        except Exception as e:  # noqa: BLE001
            print(f"[TG] cycle err: {e}")
        time.sleep(CYCLE_SEC)
