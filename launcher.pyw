# v3.3 no-focus launcher. Watchdog + updater for Propr Live. Relaunches the widget if it exits unexpectedly.
import os, sys, time, subprocess, json, urllib.request, re
HERE = os.path.dirname(os.path.abspath(__file__)); W = os.path.join(HERE, "propr_widget.pyw")
FLAG = os.path.join(HERE, "closed_by_user.flag"); LOG = os.path.join(HERE, "launcher.log")
PY = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
if not os.path.exists(PY): PY = sys.executable
def log(m):
    try: open(LOG, "a").write(time.strftime("%Y-%m-%d %H:%M:%S ") + m + "\n")
    except Exception: pass
def ver(s):
    m = re.search(r'VERSION\s*=\s*"([\d.]+)"', s); return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)
def update():
    try: url = json.load(open(os.path.join(HERE, "config.json"))).get("update_url", "")
    except Exception: url = ""
    if not url: return False
    try:
        new = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "PropWidget"}), timeout=15).read().decode()
        cur = open(W, encoding="utf-8").read()
        if ver(new) > ver(cur) and "tkinter" in new:
            compile(new, W, "exec"); open(W, "w", encoding="utf-8").write(new); log("updated"); return True
    except Exception as e: log("update check failed: " + str(e)[:80])
    return False
# single instance via lock port
GAME = os.path.join(HERE, "game_mode.flag")
def gaming():  # widget writes this while a fullscreen app is foreground; stale (>30s) flag ignored
    try: return time.time() - os.path.getmtime(GAME) < 30 or _fs()
    except OSError: return _fs()
def _fs():
    try:
        import ctypes; u = ctypes.windll.user32
        class R(ctypes.Structure): _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]
        u.GetForegroundWindow.restype = ctypes.c_void_p; fg = u.GetForegroundWindow()
        if not fg: return False
        cls = ctypes.create_unicode_buffer(64); u.GetClassNameW(ctypes.c_void_p(fg), cls, 64)
        if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd", "TkTopLevel"): return False
        r = R(); u.GetWindowRect(ctypes.c_void_p(fg), ctypes.byref(r))
        return r.l <= 0 and r.t <= 0 and r.r >= u.GetSystemMetrics(0) and r.b >= u.GetSystemMetrics(1)
    except Exception: return False
def spawn():
    kw = {}
    if os.name == "nt":
        si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow = 4  # SW_SHOWNOACTIVATE
        kw = dict(startupinfo=si, creationflags=0x08000000)  # CREATE_NO_WINDOW
    return subprocess.Popen([PY, W], cwd=HERE, **kw)
import socket
s = socket.socket()
try: s.bind(("127.0.0.1", 47913))
except OSError: sys.exit(0)
if os.path.exists(FLAG): os.remove(FLAG)
update(); last = time.time(); fails = 0
while True:
    while gaming(): time.sleep(5)   # never (re)launch over a fullscreen game
    p = spawn(); started = time.time()
    while p.poll() is None:
        time.sleep(5)
        if time.time() - last > 1800 and not gaming():
            last = time.time()
            if update():
                while gaming(): time.sleep(5)
                log("restarting for update"); p.terminate(); p.wait()
    if os.path.exists(FLAG): os.remove(FLAG); log("closed by user"); break
    fails = fails + 1 if time.time() - started < 30 else 0
    log(f"widget exited ({p.returncode}), relaunching"); time.sleep(min(60, 3 * (fails + 1)))
