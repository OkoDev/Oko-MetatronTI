"""Доказательство, что ускорение impulses_on_bar ничего не изменило (Егор: «перенести стоит, если не сломает ничего»).
Сравнивает ТЕКУЩИЙ боевой код с версией из git HEAD на всех барах: оба режима merge, четыре ТФ, N монет.
Сверяются не только импульсы, но и итоговые сетапы mark_impulse — то, чем пользуются бот, тень и терминал."""
import sys, subprocess, importlib.util, random, time
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT))
from tfcache import load_tf, PARQ


def git_head_module():
    """Версия wave5_core из последнего коммита — эталон «как было»."""
    src = subprocess.run(["git", "show", "HEAD:core/waves/wave5_core.py"], cwd=ROOT,
                         capture_output=True, text=True, encoding="utf-8").stdout
    p = Path(__file__).with_name("_wave5_core_head.py")
    p.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("wave5_core_head", p)
    m = importlib.util.module_from_spec(spec)
    sys.modules["wave5_core_head"] = m          # dataclass внутри ищет свой модуль в sys.modules
    spec.loader.exec_module(m)
    return m


def main(n_syms=25):
    import core.waves.wave5_core as NEW
    from core.smc.oko_sm_engine import _swings
    OLD = git_head_module()
    syms = sorted(p.stem for p in PARQ.glob("*.parquet"))
    random.Random(17).shuffle(syms); syms = syms[:n_syms]
    P = NEW.WaveParams()
    bad = 0; checked = 0; t_old = t_new = 0.0
    for tf in ("4h", "1h", "15m"):
        for sym in syms:
            try:
                d = load_tf(sym, tf)
            except Exception:
                continue
            if len(d) < 600:
                continue
            x = d.reset_index(drop=True)
            hh, lh = x.high.values.astype(float), x.low.values.astype(float)
            sws = _swings(x["high"], x["low"], P.sw)
            step = max(1, len(x) // 4000)                       # до 4000 баров на монету/ТФ
            bars = range(300, len(x), step)
            for merge in (False, True):
                t0 = time.time()
                a = [OLD.impulses_on_bar(sws, b, hh, lh, merge=merge) for b in bars]
                t_old += time.time() - t0
                t0 = time.time()
                c = [NEW.impulses_on_bar(sws, b, hh, lh, merge=merge) for b in bars]
                t_new += time.time() - t0
                checked += len(a)
                if repr(a) != repr(c):
                    bad += 1
                    print(f"  РАСХОЖДЕНИЕ: {sym} {tf} merge={merge}")
    print(f"impulses_on_bar: сверено {checked:,} вызовов на {len(syms)} монетах × 3 ТФ × 2 режима merge · "
          f"расхождений {bad} · было {t_old:.1f}с, стало {t_new:.1f}с (×{t_old / max(t_new, 1e-6):.0f})")

    # сквозная проверка: итоговые сетапы mark_impulse на последних барах (это то, что видит бот)
    diff = 0; tot = 0
    for tf in ("4h", "1h"):
        for sym in syms:
            try:
                d = load_tf(sym, tf)
            except Exception:
                continue
            for cut in (0, 37, 111):
                dd = d.iloc[:len(d) - cut] if cut else d
                now = dd.index[-1] + pd.Timedelta(minutes=NEW.TF_MIN[tf])
                for lb in (0, 24):
                    ra = OLD.mark_impulse(dd, now, P, tf, lookback=lb)
                    rb = NEW.mark_impulse(dd, now, P, tf, lookback=lb)
                    tot += 1
                    if repr(ra) != repr(rb):
                        diff += 1; print(f"  РАСХОЖДЕНИЕ mark_impulse: {sym} {tf} cut={cut} lookback={lb}")
    print(f"mark_impulse: сверено {tot} разметок · расхождений {diff}")
    print("ИТОГ:", "идентично" if bad == 0 and diff == 0 else "ЕСТЬ РАСХОЖДЕНИЯ")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 25)
