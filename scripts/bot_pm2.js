// Бот под pm2 (08.07, «+» Егора: фоновый автозапуск без терминала).
// pm2_resurrect в автозагрузке Windows → бот стартует при старте системы вместе со
// всей инфраструктурой. Дубль из терминала отсечёт single-instance lock (stale-фикс 08.07).
const { spawn } = require("child_process");
const p = spawn(
  "C:\\Users\\yogoru\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
  ["oko_mtf.py"],
  {
    cwd: "e:\\MTF BOT\\CURSOR\\crypto_volume_bot",
    // OKO_PM2_WRAPPER_PID (15.09): бот следит за этой обёрткой и выходит сам, когда pm2 её завершает — иначе python
    // оставался сиротой с bot_instance.lock и pm2 уходил в цикл рестартов (oko_mtf._start_pm2_parent_watchdog)
    env: { ...process.env, PYTHONIOENCODING: "utf-8", OKO_PM2_WRAPPER_PID: String(process.pid) },   // cp1251 роняла Δ/→ в print
    stdio: "inherit",
    windowsHide: true,   // без этого node-spawn открывает видимое консольное окно (08.07)
  },
);
p.on("exit", (code) => process.exit(code ?? 0));
