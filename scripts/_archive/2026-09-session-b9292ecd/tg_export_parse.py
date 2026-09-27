"""Парсер HTML-экспорта Telegram Desktop (ChatExport) → DataFrame постов: id, время, автор, текст, фото, reply_to.
Использование: python tg_export_parse.py <папка экспорта> → G:/oko_lab/out/tg_jewtrade/posts.pkl + сводка."""
import sys, re, glob, html
from pathlib import Path
import pandas as pd

MSG_RE = re.compile(r'<div class="message default clearfix(?: joined)?" id="message(?P<id>\d+)">(?P<body>.*?)(?=<div class="message (?:default|service)|</div>\s*</div>\s*</div>\s*<!--|$)', re.S)
DATE_RE = re.compile(r'<div class="pull_right date details" title="(?P<dt>[^"]+)"')
FROM_RE = re.compile(r'<div class="from_name">\s*(?P<name>.*?)\s*</div>', re.S)
TEXT_RE = re.compile(r'<div class="text">(?P<text>.*?)</div>', re.S)
PHOTO_RE = re.compile(r'class="photo_wrap[^"]*"\s+href="([^"]+)"')
REPLY_RE = re.compile(r'In reply to <a href="#go_to_message(\d+)"')


def parse_file(p: Path, last_name=[None]):
    h = p.read_text(encoding="utf-8", errors="ignore")
    out = []
    # разбивка по началу сообщений
    parts = re.split(r'(?=<div class="message default clearfix)', h)
    for part in parts[1:]:
        m_id = re.match(r'<div class="message default clearfix(?: joined)?" id="message(\d+)">', part)
        if not m_id:
            continue
        mid = int(m_id.group(1))
        dt = DATE_RE.search(part); fr = FROM_RE.search(part)
        name = html.unescape(re.sub("<[^>]+>", "", fr.group("name"))).strip() if fr else last_name[0]
        last_name[0] = name
        tx = TEXT_RE.search(part)
        text = ""
        if tx:
            t = tx.group("text"); t = re.sub(r"<br\s*/?>", "\n", t); t = re.sub("<[^>]+>", "", t); text = html.unescape(t).strip()
        photos = PHOTO_RE.findall(part); rp = REPLY_RE.search(part)
        out.append({"id": mid, "dt": pd.to_datetime(dt.group("dt")[:19], format="%d.%m.%Y %H:%M:%S") if dt else pd.NaT,
                    "from": name, "text": text, "n_photos": len(photos), "photo": photos[0] if photos else None,
                    "reply_to": int(rp.group(1)) if rp else None, "file": p.name})
    return out


if __name__ == "__main__":
    root = Path(sys.argv[1])
    files = sorted(root.glob("messages*.html"), key=lambda p: (len(p.stem), p.stem))
    rows = []
    for f in files:
        rows += parse_file(f)
    d = pd.DataFrame(rows).drop_duplicates("id").sort_values("id").reset_index(drop=True)
    out = Path("G:/oko_lab/out/tg_jewtrade"); out.mkdir(parents=True, exist_ok=True); d.to_pickle(out / "posts.pkl")
    print(f"файлов {len(files)} · постов {len(d)} · {d.dt.min()} → {d.dt.max()} · с текстом {int((d.text.str.len() > 0).sum())} · с фото {int((d.n_photos > 0).sum())}")
    print(d["from"].value_counts().head(5).to_dict())
    print(d.groupby(d.dt.dt.to_period("M")).size().to_string())
    for r in d[d.text.str.len() > 0].sample(6, random_state=1).itertuples():
        print(f"\n[{r.dt}] {r.text[:400]}")
