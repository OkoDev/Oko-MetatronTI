"""
Тест латентности прокси к BingX — ЗАПУСКАТЬ ИЗ СВОЕГО ТЕРМИНАЛА (не через Claude).
Claude-среда под sandbox-firewall (codex_sandbox_offline_block_outbound) → даёт ложный 10013.
Реальный бот/твой терминал — без этого правила, покажет настоящую латентность.

Запуск:
    python scripts/test_proxy_latency.py
"""
import requests
import time

IPS = ["172.120.69.214", "172.120.69.17", "172.120.69.15"]
USER, PWD = "yogoru", "CHfyWVM3GE"
PORT = 59100  # HTTP(s)
URL = "https://open-api.bingx.com/openApi/swap/v2/server/time"

print("=== латентность прокси к BingX (после split-tunnel, прямой путь РФ→Сингапур) ===")
for ip in IPS:
    px = f"http://{USER}:{PWD}@{ip}:{PORT}"
    ts = []
    code = "?"
    for _ in range(4):
        t = time.time()
        try:
            r = requests.get(URL, proxies={"https": px, "http": px}, timeout=12)
            ts.append((time.time() - t) * 1000)
            code = r.status_code
        except Exception as e:
            ts.append(None)
            code = f"ERR {type(e).__name__}: {str(e)[:45]}"
    good = [x for x in ts if x]
    if good:
        print(f"  {ip}: avg={sum(good)/len(good):.0f}ms  min={min(good):.0f}ms  http={code}")
    else:
        print(f"  {ip}: FAIL — {code}")

# выходной IP (должен = прокси-IP, подтверждает обход per-IP лимита BingX)
print("\n=== выходной IP через прокси (должен быть прокси-IP, не VPN-Амстердам) ===")
for ip in IPS[:1]:
    px = f"http://{USER}:{PWD}@{ip}:{PORT}"
    try:
        r = requests.get("https://api.ipify.org", proxies={"https": px, "http": px}, timeout=10)
        print(f"  через {ip} → выходной IP: {r.text}")
    except Exception as e:
        print(f"  ERR: {e}")

print("\nОжидаемо: latency <300ms (Сингапур→BingX близко). Если так — прокси готовы к интеграции.")
print("Если FAIL — Windows Firewall режет прямой доступ (нужно outbound-правило allow для порта 59100).")
