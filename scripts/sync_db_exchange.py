"""Синхрон БД↔биржа: закрыть БД-OPEN сделки которых нет на бирже (orphans→EXPIRED)."""
import sys; sys.path.insert(0, r"e:/MTF BOT/CURSOR/crypto_volume_bot"); sys.stdout.reconfigure(encoding='utf-8')
import asyncio, sqlite3
from dotenv import load_dotenv; load_dotenv()
from core.exchange.bingx_client import make_client, to_bingx_symbol
class Cfg:
    def get(self,k,d=''): return d
async def main():
    live=set()
    for acc in [1,2]:  # main + sub
        c=make_client('vst',Cfg(),account=acc)
        if not c: continue
        await c.sync_time()
        try:
            for p in await c.get_positions():
                if float(p.get('positionAmt',0) or 0)!=0:
                    live.add((p.get('symbol'),p.get('positionSide','').upper()))
        except Exception as e: print(f'acc{acc} err {e}')
    con=sqlite3.connect('subscriptions.db')
    rows=con.execute("SELECT id,symbol,direction FROM simulated_trades WHERE status='OPEN'").fetchall()
    orph=[id for id,s,d in rows if (to_bingx_symbol(s),(d or '').upper()) not in live]
    if orph:
        ph=','.join('?'*len(orph))
        con.execute(f"UPDATE simulated_trades SET status='EXPIRED',R_multiple=0,closed_at=datetime('now') WHERE id IN ({ph})",orph)
        con.commit()
    n=con.execute("SELECT COUNT(*) FROM simulated_trades WHERE status='OPEN'").fetchone()[0]
    print(f'биржа(main+sub)={len(live)} | закрыто orphans={len(orph)} | БД OPEN={n} | синхрон={n==len(live)}')
asyncio.run(main())
