"""Докачка 1m до актуальных с максимальным покрытием (Егор 16.09).
Источник — публичные архивы data.binance.vision (без ключей): месячные до последнего закрытого месяца, дальше дневные.
Для монет, что уже есть, качаются только недостающие периоды; новые монеты качаются с даты листинга (onboardDate из
fapi exchangeInfo — иначе тысячи лишних 404). Пишет в C:\\oko_data\\history\\1m (через junction C:\\oko_history\\1m).
Запуск: python fetch_update.py [update|new|all] [потоков]"""
import io, json, sys, time, zipfile, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd

OUT = Path(r"C:\oko_history\1m")
MON = "https://data.binance.vision/data/futures/um/monthly/klines/{s}/1m/{s}-1m-{d}.zip"
DAY = "https://data.binance.vision/data/futures/um/daily/klines/{s}/1m/{s}-1m-{d}.zip"
# 17.09 (Егор: «самые полные архивы хранятся в отношении к USD»): фьючерсный архив начинается с листинга
# ФЬЮЧЕРСА, спотовый — с листинга монеты. У BTC спот с 2017, у ADA с 2018, у LINK с 2019, фьючерсов там нет.
# Для ранних месяцев берём спот: ряд цены тот же (базис доли процента), а два альтсезона (2017-18 и 2021)
# иначе непроверяемы. Склейка честно помечается в логе.
MON_SPOT = "https://data.binance.vision/data/spot/monthly/klines/{s}/1m/{s}-1m-{d}.zip"
# 17.09 (Егор: «докачать с 2020 года»): окно расширено назад — в 2020-21 был альтсезон с иксами,
# а все наши замеры стояли на 2022-12+, где пампов почти нет. Механика продолжения (каскадный TSL)
# без этих лет непроверяема: она бережёт хвост, которого в нашем окне не случалось.
START = pd.Timestamp("2017-08-01")     # раньше спотовых архивов Binance нет
TODAY = pd.Timestamp.utcnow().tz_localize(None).normalize()


def http(url, timeout=60):
    for i in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1 + 2 * i)
        except Exception:
            time.sleep(1 + 2 * i)
    return None


def chunk(sym, url):
    raw = http(url)
    if not raw and "/futures/um/monthly/" in url:
        raw = http(url.replace("/futures/um/monthly/", "/spot/monthly/"))   # фьючерса ещё не было — берём спот
    if not raw:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            txt = z.read(z.namelist()[0])
        df = pd.read_csv(io.BytesIO(txt), header=None, usecols=range(6))
        if not str(df.iloc[0, 0]).isdigit():
            df = df.iloc[1:]
        df.columns = ["t", "open", "high", "low", "close", "volume"]
        df = df.astype({"t": "int64", "open": float, "high": float, "low": float, "close": float, "volume": float})
        df.index = pd.to_datetime(df.t, unit="ms", utc=True).dt.tz_localize(None)   # naive UTC, как в существующих
        return df[["open", "high", "low", "close", "volume"]]
    except Exception:
        return None


def periods(sym, src, t_from):
    """Месяцы целиком, пока месяц закрыт; хвост текущего месяца — днями."""
    out = []
    m_last = (TODAY.to_period("M") - 1).to_timestamp()            # последний закрытый месяц
    for p in pd.period_range(max(t_from, START).to_period("M"), m_last.to_period("M"), freq="M"):
        out.append(MON.format(s=src, d=str(p)))
    d0 = max(t_from.normalize(), m_last.to_period("M").to_timestamp() + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1))
    for d in pd.date_range(d0, TODAY - pd.Timedelta(days=1), freq="D"):
        out.append(DAY.format(s=src, d=f"{d:%Y-%m-%d}"))
    return out


def one(job):
    sym, src, onboard = job
    p = OUT / f"{sym}.parquet"
    old = None
    urls = []
    if p.exists():
        old = pd.read_parquet(p)
        if getattr(old.index, "tz", None) is not None:
            old.index = old.index.tz_convert("UTC").tz_localize(None)
        # докачка НАЗАД: окно расширено до 2020, а файлы собирались с 2022-12 — тянем недостающие
        # месяцы до первого имеющегося бара (с даты листинга монеты, раньше архивов нет)
        first_have = old.index[0]
        # вглубь идём до фактического начала истории монеты, а не до листинга фьючерса: у спота
        # архивы старше. Останавливаемся, когда три месяца подряд пустые — дальше истории нет.
        if first_have > START + pd.Timedelta(days=35):
            miss = 0
            for pr in reversed(list(pd.period_range(START.to_period("M"),
                                                    (first_have - pd.Timedelta(days=1)).to_period("M"), freq="M"))):
                u = MON.format(s=src, d=str(pr))
                if http(u, timeout=20) is None and http(u.replace("/futures/um/monthly/", "/spot/monthly/"), timeout=20) is None:
                    miss += 1
                    if miss >= 3:
                        break
                    continue
                miss = 0
                urls.append(u)
        t_from = old.index[-1].normalize().to_period("M").to_timestamp()           # перекачиваем текущий месяц целиком
        if old.index[-1] < TODAY - pd.Timedelta(days=1):
            urls += periods(sym, src, t_from)
        elif not urls:
            return sym, "актуально"
    else:
        t_from = max(pd.Timestamp(onboard, unit="ms").normalize(), START) if onboard else START
        urls = periods(sym, src, t_from)
    if not urls:
        return sym, "нечего качать"
    parts = []
    with ThreadPoolExecutor(6) as ex:
        for df in ex.map(lambda u: chunk(sym, u), urls):
            if df is not None and len(df):
                parts.append(df)
    if not parts:
        return sym, f"пусто ({len(urls)} архивов, все 404)"
    new = pd.concat(parts)
    if old is not None:
        new = pd.concat([old, new])
    new = new[~new.index.duplicated(keep="last")].sort_index()
    new.to_parquet(p)
    return sym, f"{len(new):,} баров {new.index[0]:%Y-%m-%d} … {new.index[-1]:%Y-%m-%d %H:%M}"


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    nproc = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    tg = json.load(open(Path(__file__).with_name("data_targets.json")))
    info = json.loads(http("https://fapi.binance.com/fapi/v1/exchangeInfo"))
    onboard = {s["symbol"]: s.get("onboardDate") for s in info["symbols"]}
    have = {p.stem for p in OUT.glob("*.parquet")}
    jobs = [(s, src, onboard.get(src)) for s, src in tg["targets"].items()
            if (mode == "all") or (mode == "update" and s in have) or (mode == "new" and s not in have)]
    jobs.sort(key=lambda j: (j[0] not in have, j[0]))            # сперва дельта по имеющимся, потом новые монеты
    print(f"режим {mode} · монет {len(jobs)} (из них новых {sum(1 for j in jobs if j[0] not in have)}) · потоков {nproc}", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(nproc) as ex:
        for i, (s, msg) in enumerate(ex.map(one, jobs), 1):
            print(f"[{i}/{len(jobs)}] {s}: {msg}", flush=True)
    gb = sum(f.stat().st_size for f in OUT.glob("*.parquet")) / 1024**3
    print(f"ГОТОВО за {(time.time() - t0) / 60:.0f} мин · паркетов {len(list(OUT.glob('*.parquet')))} · {gb:.1f} ГБ", flush=True)
