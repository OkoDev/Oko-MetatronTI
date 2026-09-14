// pm2 start scripts/pm2_wave5_shadow.config.js · pm2 save
// Тень-форвард ядра волн: полная разметка после закрытия 4h-бара, лёгкий цикл каждые 15 мин.
module.exports = {
  apps: [{
    name: "wave5-shadow",
    script: "C:\\Users\\yogoru\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
    args: "scripts/wave5_shadow.py --loop --universe bingx --min_vol 2e6 --draw",
    cwd: "E:\\MTF BOT\\CURSOR\\crypto_volume_bot",
    interpreter: "none",
    autorestart: true,
    restart_delay: 30000,
    max_restarts: 50,
    env: { PYTHONIOENCODING: "utf-8", PYTHONUNBUFFERED: "1" },
    out_file: "E:\\MTF BOT\\CURSOR\\crypto_volume_bot\\data\\wave5_shadow\\pm2_out.log",
    error_file: "E:\\MTF BOT\\CURSOR\\crypto_volume_bot\\data\\wave5_shadow\\pm2_err.log",
    merge_logs: true,
    time: true
  }]
};
