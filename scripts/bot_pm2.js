// Бот под pm2 (08.07, «+» Егора: фоновый автозапуск без терминала).
// pm2_resurrect в автозагрузке Windows → бот стартует при старте системы вместе со
// всей инфраструктурой. Дубль из терминала отсечёт single-instance lock (stale-фикс 08.07).
const { spawn } = require("child_process");
const p = spawn(
  "C:\\Users\\yogoru\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
  ["oko_mtf.py"],
  {
    cwd: "e:\\MTF BOT\\CURSOR\\crypto_volume_bot",
    env: { ...process.env, PYTHONIOENCODING: "utf-8" },   // cp1251 роняла Δ/→ в print
    stdio: "inherit",
    windowsHide: true,   // без этого node-spawn открывает видимое консольное окно (08.07)
  },
);
p.on("exit", (code) => process.exit(code ?? 0));
