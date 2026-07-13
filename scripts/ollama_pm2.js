// Ollama под pm2 (08.07): модель СТРОГО на GTX 1070 — 1080 держит винду/мониторы
// (BSOD 0x10E 08.07 при инициализации обеих карт; 1070 полностью свободна: 0 MiB).
// UUID вместо индекса — не зависит от порядка нумерации CUDA. env только у ЭТОГО
// процесса — глобальный setx сломал бы DaVinci/CUDA-приложения (им нужна 1080).
const { spawn } = require("child_process");
const p = spawn(
  "C:\\Users\\yogoru\\AppData\\Local\\Programs\\Ollama\\ollama.exe", ["serve"],
  {
    env: {
      ...process.env,
      // ⚠️ ИЗВЕСТНЫЙ БАГ ollama (issue #9722, актуален в 0.30): выбор GPU НЕ работает —
      // проверены 08.07 UUID, PCI-индекс (эти строки) и options.main_gpu: модель всегда
      // ложится на 1080. РЕШЕНИЕ (осознанное): модель живёт на 1080 — влезает целиком
      // (5.8/8.2GB при винде 0.4GB), KEEP_ALIVE 10m сам освобождает VRAM через 10 мин
      // простоя. Правило эксплуатации: не гонять LLM одновременно с тяжёлым DaVinci.
      // Строки ниже оставлены: починят баг → изоляция на 1070 включится сама.
      CUDA_DEVICE_ORDER: "PCI_BUS_ID",
      CUDA_VISIBLE_DEVICES: "0",                        // GTX 1070 (когда баг починят)
      OLLAMA_MAX_LOADED_MODELS: "1",
      OLLAMA_KEEP_ALIVE: "10m",
    },
    stdio: "inherit",
    windowsHide: true,   // без этого node-spawn открывает видимое консольное окно (08.07)
  },
);
p.on("exit", (code) => process.exit(code ?? 0));
