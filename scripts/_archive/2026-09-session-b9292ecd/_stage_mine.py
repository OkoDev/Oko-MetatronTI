"""Стейджит только МОИ хунки (содержат маркер «19.09») в файлах, где лежат чужие незакоммиченные правки."""
import subprocess, sys, re
ROOT = r"E:\MTF BOT\CURSOR\crypto_volume_bot"
files = sys.argv[1:]
MARK = ("19.09", "все на канон", "канон", "ote_band", "OTE_TOP", "SNAP_SCHEMA_VERSION = 3")
out = []
for f in files:
    diff = subprocess.run(["git", "diff", "--", f], cwd=ROOT, capture_output=True).stdout.decode("utf-8", "replace")
    if not diff.strip():
        continue
    head, *hunks = re.split(r"(?m)^(?=@@ )", diff)
    keep = [h for h in hunks if any(m in l for l in h.splitlines() if l.startswith("+") for m in MARK)]
    print(f"{f}: хунков {len(hunks)}, моих {len(keep)}")
    if keep:
        out.append(head + "".join(keep))
patch = "".join(out)
open(r"C:\Users\yogoru\AppData\Local\Temp\claude\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad\_mine.patch", "w", encoding="utf-8", newline="\n").write(patch)
r = subprocess.run(["git", "apply", "--cached", "--recount", "-"], cwd=ROOT, input=patch.encode("utf-8"), capture_output=True)
print("apply:", r.returncode, r.stderr.decode("utf-8", "replace")[:400])
