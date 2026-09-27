"""ЧТЕНИЕ: реальные реализованные PnL на VST за период простоя (24-25.09) против записей БД.
Простой 24.09 04:22 → 25.09 16:58 МСК: бот не фиксировал стопы. Вопрос — закрылись ли позиции
на бирже вовремя (по биржевому SL) и совпадают ли деньги с тем, что записано в simulated_trades."""
import asyncio, sqlite3, sys
from pathlib import Path
import pandas as pd

ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT))
import logging; logging.disable(logging.CRITICAL)
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from core.infra.config_loader import config              # noqa: E402
from core.exchange.bingx_client import make_client       # noqa: E402

T0 = pd.Timestamp("2026-09-23T12:00:00Z")
T1 = pd.Timestamp("2026-09-26T00:00:00Z")


async def main():
    rows = []
    for acc in (1, 2):
        cli = make_client("vst", config, account=acc)
        if cli is None:
            continue
        try:
            await cli.sync_time(force=True)      # без синхронизации времени income приходит пустым
            inc = await cli.get_income(int(T0.timestamp() * 1000), int(T1.timestamp() * 1000), limit=1000)
            for it in (inc or []):
                rows.append({
                    "acc": acc,
                    "symbol": it.get("symbol"),
                    "type": it.get("incomeType"),
                    "amount": float(it.get("income") or 0),
                    "ts": pd.to_datetime(int(it.get("time") or 0), unit="ms", utc=True),
                })
        except Exception as e:                            # noqa: BLE001
            print(f"аккаунт {acc}: ошибка get_income — {e}")
        finally:
            try:
                await cli.close()
            except Exception:                              # noqa: BLE001
                pass

    if not rows:
        print("записей income нет")
        return
    d = pd.DataFrame(rows).sort_values("ts")
    print(f"записей income: {len(d)}  ({d.ts.min()} → {d.ts.max()})")
    print("\nпо типам:")
    print(d.groupby("type").amount.agg(["count", "sum"]).round(3).to_string())

    pnl = d[d.type.str.upper().str.contains("REALIZED", na=False)]
    if not pnl.empty:
        print(f"\nРЕАЛИЗОВАННЫЙ PnL на VST за период: {pnl.amount.sum():+.2f} USDT")
        print("\nпо монетам (топ убытков):")
        g = pnl.groupby("symbol").amount.agg(["count", "sum"]).sort_values("sum")
        print(g.head(12).round(3).to_string())
        print("\nзакрытия за сутки простоя (24.09):")
        day = pnl[(pnl.ts >= "2026-09-24") & (pnl.ts < "2026-09-25")]
        print(f"  сделок {len(day)}, сумма {day.amount.sum():+.2f} USDT")

    # что записано в БД по тем же 8 шортам
    c = sqlite3.connect(ROOT / "subscriptions.db")
    q = ("select symbol, round(profit_pct,2) from simulated_trades "
         "where signal_type='impulse_fib_15m' and closed_at like '2026-09-25T13:59%'")
    print("\nв БД записано (profit_pct):")
    for sym, p in c.execute(q):
        bx = sym.split("/")[0] + "-USDT"
        real = pnl[pnl.symbol == bx] if not pnl.empty else pd.DataFrame()
        rt = f"биржа: {real.amount.sum():+.3f} USDT в {str(real.ts.max())[5:16]}" if len(real) else "на бирже закрытий не видно"
        print(f"  {sym:<18}{p:>7}%   {rt}")


asyncio.run(main())
