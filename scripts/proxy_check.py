#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Проверка пула прокси ПЕРЕД включением: подсети, живость, латентность к BingX.

Повод (02.09.2026): текущие три прокси в .env оказались в ОДНОЙ /24
(172.120.69.{214,17,15}). Троттлинг BingX накапливается по IP, и если провайдер
выдаёт адреса одной подсети, десять штук могут работать как один
([[bingx_soft_throttle_by_ip]]).

Запуск:
    python scripts/proxy_check.py            # берёт PROXY_LIST из .env
    python scripts/proxy_check.py --live     # + реальные запросы к BingX через каждый
"""
import argparse
import asyncio
import collections
import io
import ipaddress
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROXY_RE = re.compile(r"(?P<scheme>\w+)://(?:(?P<user>[^:@]+):(?P<pw>[^@]+)@)?"
                      r"(?P<host>[\w.\-]+):(?P<port>\d+)")


def read_list() -> list:
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.exists(path):
        print("🔴 .env не найден")
        return []
    raw = ""
    for line in io.open(path, encoding="utf-8", errors="ignore"):
        if line.strip().startswith("PROXY_LIST"):
            raw = line.split("=", 1)[1].strip()
    return [p.strip() for p in raw.split(",") if p.strip()]


def audit(proxies: list) -> None:
    print(f"ПУЛ: {len(proxies)} прокси\n")
    nets24, nets16, schemes, fam = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
    parsed = []
    for p in proxies:
        m = PROXY_RE.match(p)
        if not m:
            print(f"  🔴 не разобран: {p[:44]}")
            continue
        host, scheme = m.group("host"), m.group("scheme")
        schemes[scheme] += 1
        try:
            ip = ipaddress.ip_address(host)
            fam[f"IPv{ip.version}"] += 1
            n24 = str(ipaddress.ip_network(f"{host}/24", strict=False)) if ip.version == 4 else "—"
            n16 = str(ipaddress.ip_network(f"{host}/16", strict=False)) if ip.version == 4 else "—"
        except ValueError:
            fam["hostname"] += 1
            n24 = n16 = "—"
        nets24[n24] += 1
        nets16[n16] += 1
        parsed.append((host, m.group("port"), n24))

    for host, port, n24 in parsed:
        dup = " 🔴 подсеть повторяется" if nets24[n24] > 1 else ""
        print(f"   {host:>16s}:{port:<6s} /24 {n24}{dup}")

    print()
    print(f"  протоколы: {dict(schemes)}   семейства: {dict(fam)}")
    print(f"  уникальных /24: {len(nets24)} из {len(parsed)}")
    print(f"  уникальных /16: {len(nets16)}")
    if parsed and len(nets24) < len(parsed):
        worst = nets24.most_common(1)[0]
        print(f"  🔴 {worst[1]} адресов в одной подсети {worst[0]} — при бане по /24 это ОДИН IP.")
        print("     Провайдер обещает замену на другие подсети — требовать.")
    elif parsed:
        print("  ✅ каждый адрес в своей /24")
    if schemes and set(schemes) - {"http", "https"}:
        print("  🔴 не-HTTP схема: код использует exchange.aiohttp_proxy, SOCKS потребует aiohttp_socks")


async def live(proxies: list) -> None:
    """Реальный запрос к BingX через каждый прокси: живость + латентность."""
    try:
        import ccxt.async_support as ccxt
    except ImportError:
        print("\n(ccxt не установлен — живая проверка пропущена)")
        return
    import statistics
    # 🔴 Прогрев обязателен: первый вызов fetch_ohlcv неявно тянет load_markets
    # (577 рынков) — без этого замер меряет загрузку справочника, а не латентность.
    print("\nЖИВАЯ ПРОВЕРКА: прогрев load_markets отдельно, затем 5 × fetch_ohlcv")

    async def probe(proxy, label):
        ex = ccxt.bingx({"enableRateLimit": True, "options": {"defaultType": "swap"}})
        if proxy:
            ex.aiohttp_proxy = proxy
        try:
            t0 = time.monotonic()
            await ex.load_markets()
            warm = (time.monotonic() - t0) * 1000
            lat = []
            for _ in range(5):
                t = time.monotonic()
                await ex.fetch_ohlcv("BTC/USDT:USDT", "1m", limit=2)
                lat.append((time.monotonic() - t) * 1000)
            print(f"   {'✅' if proxy else '──'} {label:>16s}  медиана {statistics.median(lat):6.0f} мс"
                  f"   мин {min(lat):5.0f}  макс {max(lat):5.0f}   (прогрев {warm:.0f})")
        except Exception as e:
            print(f"   🔴 {label:>16s}  {type(e).__name__}: {str(e)[:60]}")
        finally:
            await ex.close()

    for p in proxies:
        m = PROXY_RE.match(p)
        await probe(p, m.group("host") if m else p[:22])
    await probe(None, "DIRECT")   # та же метрика напрямую — честная база


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="реальные запросы к BingX через каждый прокси")
    a = ap.parse_args()
    proxies = read_list()
    if not proxies:
        print("PROXY_LIST пуст")
        return
    audit(proxies)
    if a.live:
        asyncio.run(live(proxies))


if __name__ == "__main__":
    main()
