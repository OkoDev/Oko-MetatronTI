"""XLM Elliott Wave chart — grand structure 1D."""
import ccxt, pandas as pd, numpy as np, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime

ex = ccxt.binance({"enableRateLimit": True, "timeout": 15000})
bars = ex.fetch_ohlcv("XLM/USDT", "1d", limit=500)
df = pd.DataFrame(bars, columns=["ts", "open", "high", "low", "close", "volume"])
df["ts"] = pd.to_datetime(df["ts"], unit="ms")
df.set_index("ts", inplace=True)

fig, ax = plt.subplots(figsize=(18, 9))
ax.plot(df.index, df["close"], color="white", linewidth=0.8, alpha=0.9)
ax.fill_between(df.index, df["low"], df["high"], alpha=0.15, color="gray")

# Dark theme
fig.patch.set_facecolor("#0d1117")
ax.set_facecolor("#0d1117")
ax.grid(True, alpha=0.15, color="white")
ax.tick_params(colors="gray")

# Wave annotations: (x_date, price, label, color)
waves = [
    ("2025-07-18", 0.5206, "W1", "#00ff88"),
    ("2026-02-06", 0.1362, "W2", "#ff4444"),
    ("2026-05-30", 0.2982, "W3", "#00ff88"),
    ("2026-06-10", 0.1811, "W4?", "#ffaa00"),
]

for date_str, price, label, color in waves:
    ax.annotate(label, xy=(pd.Timestamp(date_str), price),
                xytext=(0, 25 if "W1" in label or "W3" in label else -25),
                textcoords="offset points", fontsize=14, fontweight="bold",
                color=color, ha="center",
                arrowprops=dict(arrowstyle="->", color=color, lw=1.5))

# W5 projection
ax.annotate("W5→?", xy=(pd.Timestamp("2026-06-30"), 0.275),
            fontsize=14, fontweight="bold", color="#00ff88", ha="center")

# Fib levels
w3_low, w3_high = 0.1362, 0.2982
for fib, lbl, clr in [(0.382, ".382", "#ffaa00"), (0.5, ".5", "#ff8800"), (0.618, ".618", "#ff4444")]:
    lvl = w3_low + (w3_high - w3_low) * fib
    ax.axhline(y=lvl, color=clr, linestyle="--", alpha=0.5, linewidth=0.8)
    ax.text(df.index[0], lvl, f"Fib {lbl} {lvl:.4f}", color=clr, fontsize=8, va="bottom")

# Current price
cur = float(df["close"].iloc[-1])
ax.axhline(y=cur, color="#00aaff", linestyle="-", alpha=0.7, linewidth=1.2)
ax.text(df.index[-1], cur, f"  ${cur:.4f}", color="#00aaff", fontsize=10, va="center", fontweight="bold")

# Labels
ax.set_title("XLM/USDT — Elliott Wave Grand Structure (1D)", color="white", fontsize=14, pad=15)
ax.set_ylabel("Price (USDT)", color="gray")

plt.tight_layout()
plt.savefig("xlm_wave_chart.png", dpi=150, facecolor="#0d1117")
print(f"Chart saved: xlm_wave_chart.png  Current: ${cur:.4f}")
