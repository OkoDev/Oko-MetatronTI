# проверка сторожа: родитель-заглушка (python sleep) → дочерний с OKO_PM2_WRAPPER_PID → убиваем родителя → потомок обязан выйти
import subprocess, sys, time, os, importlib.util
if len(sys.argv) > 1 and sys.argv[1] == "child":
    sys.path.insert(0, r"E:\MTF BOT\CURSOR\crypto_volume_bot")
    spec = importlib.util.spec_from_file_location("okom", r"E:\MTF BOT\CURSOR\crypto_volume_bot\oko_mtf.py")
    src = open(r"E:\MTF BOT\CURSOR\crypto_volume_bot\oko_mtf.py", encoding="utf-8").read().split('if __name__ == "__main__":')[0]
    ns = {"__file__": r"E:\MTF BOT\CURSOR\crypto_volume_bot\oko_mtf.py", "__name__": "okom"}
    os.chdir(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
    exec(compile(src, "oko_mtf_head", "exec"), ns)
    lock = os.path.join(os.environ["TMPD"], "t.lock"); open(lock, "w").write(str(os.getpid()))
    ns["_start_pm2_parent_watchdog"](lock)
    time.sleep(120); print("НЕ ВЫШЕЛ"); sys.exit(0)
tmpd = os.path.dirname(os.path.abspath(__file__))
parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
env = {**os.environ, "OKO_PM2_WRAPPER_PID": str(parent.pid), "TMPD": tmpd}
child = subprocess.Popen([sys.executable, __file__, "child"], env=env)
time.sleep(15)
print("через 15 с при живом родителе потомок жив:", child.poll() is None)
parent.kill(); t0 = time.time()
try:
    rc = child.wait(timeout=30); print("потомок вышел rc", rc, "за", round(time.time() - t0, 1), "с; lock снят:", not os.path.exists(os.path.join(tmpd, "t.lock")))
except subprocess.TimeoutExpired:
    child.kill(); print("ПРОВАЛ: потомок не вышел")
