# 🎨 V0 PROMPT — OKO Dashboard (Cyberpunk + Metatron's Cube)

> Промпт для v0.app. Эстетика: киберпанк + сакральная геометрия Куба Метатрона.
> Стек: Next.js + Tailwind + shadcn. Тёмная тема, мобильный. Отдать v0 целиком (англ).

---

## PROMPT (copy to v0)

```
Build a dark cyberpunk trading dashboard called "OKO" (the All-Seeing Eye) — a quantum
trading command center where market data feels like sacred cosmic geometry. The aesthetic
fuses CYBERPUNK NEON with SACRED GEOMETRY (Metatron's Cube). This is NOT a corporate finance
app — it is a "sacred-tech temple" for an algorithmic trader. Trading as reading the geometry
of the cosmos.

=== VISUAL IDENTITY ===
- Background: near-black, deep space (#06060B / #0A0A14), with a faint Metatron's Cube
  line-art watermark (13 circles + connecting lines) glowing very subtly behind content.
- Neon palette (glowing): magenta/purple #B14AED, electric violet #C04AFF, cyan #22D3EE,
  electric blue #3B82F6, gold #E8B923, neon green #2DD4BF (ML), orange #FB923C (signals).
- Heavy use of GLOW / BLOOM on neon elements, GLASSMORPHISM panels (frosted dark glass,
  1px glowing gradient borders, subtle inner shadow).
- HUD / sci-fi framing: corner brackets on panels, thin scanline texture overlay, animated
  thin glowing borders, occasional "data stream" tickers.
- Logo motif: an all-seeing EYE inside a triangle, neon outline, top-left of sidebar.
- Typography: geometric futuristic sans for headings (Orbitron or Rajdhani feel),
  monospace (JetBrains Mono) for ALL numbers, prices, R-multiples and data.
- Numbers animate (count-up / split-flap flip) on update. Live "pulse" dots for active state.
- Platonic solids (cube, octahedron, tetrahedron, icosahedron, dodecahedron) as subtle
  decorative wireframe icons in section headers / footer.

=== LAYOUT ===
- Collapsible LEFT SIDEBAR, dark glass, neon glowing active item (left accent bar + glow).
  Nav items with line-icons: Overview, Cube, Trades, Pairs, Patterns, Signals, Analytics,
  Settings.
- TOP BAR: OKO eye-logo + "OKO" wordmark, page title, date-range chip, search, a live
  "SYSTEM: LIVE" pulse indicator, notifications bell, profile avatar.
- Main area: responsive grid, generous spacing, mobile-first (cards stack on phone).

=== SIGNATURE COMPONENT: "THE CUBE" (most important screen) ===
A full interactive Metatron's-Cube visualization as the centerpiece. 13 glowing spheres
arranged in the classic Metatron's Cube pattern, connected by thin glowing lines (the
"Shared Context Bus"). The central sphere is the BUS (brightest). Each outer sphere is a
"sphere of the cube" (e.g. Data, Signals, Context, ML, Execution, Feedback) — color-coded,
softly pulsing with activity, with a tiny live metric label. Hovering a sphere highlights
its connections; clicking opens a side panel with that sphere's live context/events.
Lines animate with traveling light pulses (data flowing). Make it feel ALIVE and cosmic.

=== SCREENS ===
1. OVERVIEW: top row of 5 neon KPI glass-cards — Total R (+xx.xR), Win Rate %, Active Trades,
   Avg R, Today R — each with sparkline + up/down neon arrow. Below: large EQUITY CURVE
   (cumulative R over time) as a glowing line + gradient area fill, cyan→magenta. Side panel:
   "Active Trades" live list with status pulse. Bottom: "Market Regime" gauge (TREND/RANGE/
   REVERSAL) and a mini Cube preview.
2. CUBE: the signature component above, full screen, with a right panel of live sphere events.
3. TRADES: dark glass data table — Pair, Direction (LONG green / SHORT red), Entry, R (mono,
   colored), Status badge (TP=green glow, SL=red glow, TSL=cyan glow, EXPIRED=gray),
   Signal type, Regime, Age. Filter chips (All/TP/SL/TSL/Open). Row click → trade detail
   drawer showing the "decision trace" (why it entered: which detectors/gates/confluence fired,
   as a vertical neon timeline). Also a KANBAN view: columns OPEN → TP1-HIT → RUNNER → CLOSING.
4. PAIRS: grid of pair cards (BTC/USDT, ETH/USDT, SOL/USDT...) each showing regime badge,
   WaveTrend mini-gauge, trend arrow, nearest OTE/pivot zone, last signal. Sparkline price.
5. PATTERNS: cards for mined patterns — name, Win Rate, Avg R, sample size n, a confidence
   ring. Sortable.
6. SIGNALS: signal-weights panel (adaptive weights per signal type as glowing horizontal
   bars), contribution breakdown donut, recent fired signals feed.
7. ANALYTICS: R-distribution histogram (neon bars), confluence breakdown, Sharpe / expectancy
   stat cards, performance by regime / timeframe heatmap.
8. SETTINGS: toggles for signal detectors and gates (neon switches), account selector,
   theme, all in glass panels.

=== MOCK DATA FLAVOR (make it feel like a real crypto algo-trader) ===
Use R-multiples (not dollars): e.g. "+12.4R", "-1.0R". Crypto pairs (BTC/USDT, ETH/USDT,
SOL/USDT, XLM/USDT, ONDO/USDT). Statuses TP / SL / TSL / EXPIRED. Signal types: confluence,
divergence, OTE, wt_signal, liquidity_sweep. Regimes: TREND_UP, TREND_DOWN, RANGE, REVERSAL.
Realistic numbers, some big runner trades (+40R), mostly small ones.

=== TECH ===
Next.js (App Router) + TypeScript + Tailwind + shadcn/ui. Charts via recharts (styled neon,
no default look). Smooth animations (framer-motion) for spheres, number count-ups, glow
pulses. Dark mode only. Fully responsive / mobile-first. Clean component structure.

=== TONE ===
Mysterious, powerful, sacred-tech. Like the cockpit of a being that reads the cosmos through
markets. Neon glow everywhere, deep cosmic dark, sacred geometry as the soul. Every screen
should feel like part of one living organism — the Cube.
```

---

## Как использовать (RU)

1. Скопируй блок выше целиком → вставь в v0.app → Generate.
2. v0 даст первый вариант (вероятно Overview + sidebar). Дальше итеративно: «now build the CUBE
   screen», «make the spheres pulse», «add the trade decision-trace drawer».
3. Куб (signature component) — проси отдельным запросом, это самое сложное и важное.
4. Если перегрузит — дроби: сначала тема+sidebar+Overview, потом по экрану.

**Палитра-эталон взята с твоих образов:** маджента/циан/золото на космической тьме, светящиеся
сферы Куба, HUD-рамки, всевидящее Око, платоновы тела. Финансовый стиль SalesOps → ушли в
киберпанк-сакральную геометрию (твой настоящий визуальный мир).
