@echo off
rem Ollama под pm2 (08.07): модель СТРОГО на GTX 1070 (GPU-0, полностью свободна) —
rem 1080 держит винду/мониторы (BSOD 0x10E 08.07 при инициализации обеих карт).
rem UUID вместо индекса — не зависит от порядка нумерации CUDA.
set CUDA_VISIBLE_DEVICES=GPU-b6740d8c-ce88-b7b5-8ead-00a09069861c
set OLLAMA_MAX_LOADED_MODELS=1
set OLLAMA_KEEP_ALIVE=10m
"C:\Users\yogoru\AppData\Local\Programs\Ollama\ollama.exe" serve
