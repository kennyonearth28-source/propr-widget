# Propr Live - mini corner terminal. Only REDUCE-ONLY orders on existing positions + cancels. Never opens positions.
VERSION = "3.4.0"
import ctypes, sys, json, os, threading, time, urllib.request, webbrowser, datetime, math, tkinter as tk, tkinter.font as tkf
HERE = os.path.dirname(os.path.abspath(__file__))
try: C = json.load(open(os.path.join(HERE, "config.json")))
except Exception: C = {}
KEY = C.get("api_key", ""); ACC = C.get("account", "urn:prp-account:qEkueeCybEma")
FAIL = float(C.get("fail_line", 9700)); TARGET = float(C.get("profit_target", 10900)); TERM = C.get("terminal_url", "https://app.propr.xyz")
API = "https://api.propr.xyz/v1"; BASE = API + "/accounts/" + ACC; STATE = os.path.join(HERE, "day_start.json")
HL = "https://api.hyperliquid.xyz/info"
W = 380
BG, CARD, CARD2, LINE = "#0b0e11", "#151a21", "#1e252f", "#2a3340"
TXT, SUB, DIM = "#eaecef", "#9aa4b2", "#5e6673"
GRN, RED, AMB, BLU = "#0ecb81", "#f6465d", "#f0b90b", "#3b82f6"
CR = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
def ulid():
    v = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big"); o = []
    for _ in range(26): o.append(CR[v & 31]); v >>= 5
    return "".join(reversed(o))
def http(url, body=None, key=True):
    h = {"User-Agent": "Mozilla/5.0 PropWidget/" + VERSION, "Accept": "application/json", "Content-Type": "application/json"}
    if key: h["X-API-Key"] = KEY
    r = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=h, method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(r, timeout=10) as f:
            t = f.read().decode(); return json.loads(t) if t else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:160]}")
def get(p): return http(BASE + p)
def n(x, d=0.0):
    try: return float(x)
    except Exception: return d
def fpx(v):
    v = n(v); a = abs(v)
    return f"{v:,.2f}" if a >= 100 else f"{v:,.4f}" if a >= 1 else f"{v:.6f}".rstrip("0")
def qty(v):
    v = n(v); return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.4g}"
SZD = {}
def szd(asset): return SZD.get(asset, 2)
def q_str(q, asset):
    d = szd(asset); m = 10 ** d; return f"{math.floor(abs(q) * m + 1e-9) / m:.{d}f}"
def p_str(p, asset):
    p = float(p)
    if p <= 0: raise ValueError("price must be > 0")
    s = float(f"{p:.5g}"); dec = max(0, 6 - szd(asset)); s = round(s, dec)
    return f"{s:.{dec}f}".rstrip("0").rstrip(".")
def day_start(eq):
    today = datetime.date.today().isoformat()
    try: s = json.load(open(STATE))
    except Exception: s = {}
    if s.get("day") != today:
        s = {"day": today, "equity": eq}
        try: json.dump(s, open(STATE, "w"))
        except Exception: pass
    return n(s.get("equity"), eq)

# ---------------- data threads ----------------
D = {"ok": None, "t": 0, "err": "", "mids": {}, "mt": 0, "a": None, "pos": [], "ords": []}
def propr_loop():
    while True:
        try:
            a = get(""); pos = [p for p in get("/positions?status=open").get("data", []) if n(p.get("quantity"))]
            ords = get("/orders?status=open").get("data", []) + get("/orders?status=pending").get("data", [])
            D.update(a=a, pos=pos, ords=ords, t=time.time(), ok=True, err="")
        except Exception as e: D.update(ok=False, err=str(e)[:80])
        time.sleep(4)
def price_loop():
    while True:
        try:
            if not SZD:
                for dex in (None, "xyz"):
                    b = {"type": "meta"}; b.update({"dex": dex} if dex else {})
                    for u in http(HL, b, key=False).get("universe", []): SZD[u["name"]] = int(u.get("szDecimals", 2))
            m = {}
            m.update(http(HL, {"type": "allMids"}, key=False)); m.update(http(HL, {"type": "allMids", "dex": "xyz"}, key=False))
            D.update(mids=m, mt=time.time())
        except Exception: pass
        time.sleep(1)
def mark(p): return n(D["mids"].get(p.get("asset")), n(p.get("markPrice")))
def upnl(p):
    sgn = 1 if (p.get("positionSide") or "").lower() == "long" else -1
    return (mark(p) - n(p.get("entryPrice"))) * abs(n(p.get("quantity"))) * sgn

# ---------------- order actions (reduce-only only) ----------------
def exit_side(p): return "sell" if (p.get("positionSide") or "").lower() == "long" else "buy"
def base_order(p, **kw):
    o = {"accountId": ACC, "exchange": "hyperliquid", "productType": "perp", "asset": p["asset"], "base": p.get("base") or p["asset"],
         "quote": "USDC", "positionId": p["positionId"], "positionSide": p["positionSide"], "intentId": ulid(),
         "side": exit_side(p), "reduceOnly": True, "closePosition": False}
    o.update(kw); return o
def post(orders):
    for o in orders:   # hard guard: never open
        if o.get("reduceOnly") is not True or not o.get("positionId"): raise RuntimeError("blocked: not reduce-only")
    return http(BASE + "/orders", {"orderGroupId": ulid(), "orders": orders})
def cancel(oid): return http(BASE + f"/orders/{oid}/cancel", {})
def brackets(p, kind):
    side = (p.get("positionSide") or "").lower()
    return [o for o in D["ords"] if o.get("type") == kind and o.get("reduceOnly") and
            (o.get("positionId") == p["positionId"] or (not o.get("positionId") and o.get("asset") == p["asset"] and (o.get("positionSide") or "").lower() == side))]
def close_part(p, frac):
    q = q_str(abs(n(p["quantity"])) * frac, p["asset"])
    if n(q) <= 0: raise RuntimeError("size too small")
    post([base_order(p, type="market", quantity=q, timeInForce="IOC", closePosition=frac >= 1)]); return f"Closed {q} {p.get('base')}"
def replace(p, kind, price):
    old = [o["orderId"] for o in brackets(p, kind)]; ps = p_str(price, p["asset"])
    post([base_order(p, type=kind, quantity=q_str(n(p["quantity"]), p["asset"]), triggerPrice=ps, timeInForce="GTC")])
    for _ in range(12):
        time.sleep(0.5)
        pend = [o for o in get("/orders?status=pending").get("data", []) if o.get("type") == kind and o["orderId"] not in old
                and abs(n(o.get("triggerPrice")) - float(ps)) <= float(ps) * 1e-6 + 1e-12]
        if pend: break
    else: return f"New {'stop' if kind=='stop_market' else 'TP'} {ps} not confirmed - old kept"
    errs = 0
    for oid in old:
        try: cancel(oid)
        except Exception: errs += 1
    return f"{'Stop' if kind=='stop_market' else 'TP'} set {ps}" + (f" ({errs} old not cancelled)" if errs else "")

# ---------------- Win32 no-focus helpers ----------------
WIN = sys.platform == "win32"
GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = -20, 0x08000000, 0x00000080, 0x00040000
SWP = 0x0001 | 0x0002 | 0x0010  # NOSIZE|NOMOVE|NOACTIVATE
if WIN:
    U32 = ctypes.windll.user32
    U32.GetParent.restype = ctypes.c_void_p; U32.GetParent.argtypes = [ctypes.c_void_p]
    U32.GetForegroundWindow.restype = ctypes.c_void_p
    U32.MonitorFromWindow.restype = ctypes.c_void_p; U32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    U32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    U32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]; U32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
    U32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]; U32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    U32.GetAncestor.restype = ctypes.c_void_p; U32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    U32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
class RECT(ctypes.Structure): _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]
class MINFO(ctypes.Structure): _fields_ = [("cb", ctypes.c_ulong), ("mon", RECT), ("work", RECT), ("flags", ctypes.c_ulong)]
def hwnd_of(w):
    try: return U32.GetParent(w.winfo_id()) or w.winfo_id()
    except Exception: return None
def set_noactivate(w, on=True):
    if not WIN: return
    try:
        h = hwnd_of(w); st = U32.GetWindowLongW(h, GWL_EXSTYLE)
        st = (st | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW if on else st & ~WS_EX_NOACTIVATE
        U32.SetWindowLongW(h, GWL_EXSTYLE, st)
    except Exception: pass
def top_noactivate(w):
    if not WIN: return
    try: U32.SetWindowPos(hwnd_of(w), ctypes.c_void_p(-1), 0, 0, 0, 0, SWP)
    except Exception: pass
OWN = set()
def fullscreen_fg():
    """True if some other app's window covers its whole monitor and is in the foreground (game mode)."""
    if not WIN: return False
    try:
        fg = U32.GetForegroundWindow()
        if not fg or fg in OWN or U32.GetAncestor(fg, 2) in OWN: return False
        cls = ctypes.create_unicode_buffer(64); U32.GetClassNameW(fg, cls, 64)
        if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd"): return False
        r = RECT(); U32.GetWindowRect(fg, ctypes.byref(r))
        mi = MINFO(); mi.cb = ctypes.sizeof(MINFO); U32.GetMonitorInfoW(U32.MonitorFromWindow(fg, 2), ctypes.byref(mi))
        m = mi.mon; return r.l <= m.l and r.t <= m.t and r.r >= m.r and r.b >= m.b
    except Exception: return False
GAME = os.path.join(HERE, "game_mode.flag")  # launcher reads this: no update restarts while it exists

# ---------------- UI ----------------
root = tk.Tk(); root.title("Propr Live"); root.overrideredirect(True)
root.attributes("-topmost", True); root.attributes("-alpha", 0.95); root.configure(bg=BG, highlightthickness=1, highlightbackground=LINE)
fams = set(tkf.families()); UI = "Segoe UI Variable Display" if "Segoe UI Variable Display" in fams else "Segoe UI"
MONO = "Cascadia Mono" if "Cascadia Mono" in fams else "Consolas"
try: g = json.load(open(os.path.join(HERE, "pos.json"))); root.geometry(f"+{g['x']}+{g['y']}")
except Exception: root.geometry("+40+40")
# v3.4 size: every font is a shared named font so +/- rescales the whole UI live
SET_F = os.path.join(HERE, "settings.json")
try: S = json.load(open(SET_F))
except Exception: S = {}
SC = {"s": min(1.6, max(0.7, float(S.get("scale", 1.0)))), "w": int(S.get("width", 0) or 0), "h": int(S.get("extra_h", 0) or 0)}
def save_set():
    try: json.dump({"scale": SC["s"], "width": SC["w"], "extra_h": SC["h"]}, open(SET_F, "w"))
    except Exception: pass
_FONTS = {}
def F(fam, size, *st):
    k = (fam, size) + st
    if k not in _FONTS: _FONTS[k] = tkf.Font(root, family=fam, size=max(5, round(size * SC["s"])), weight="bold" if "bold" in st else "normal")
    return _FONTS[k]
def WW(): return SC["w"] or round(W * SC["s"])   # current window width in px
def L(par, text="", fg=TXT, font=None, bg=CARD, **kw): return tk.Label(par, text=text, fg=fg, bg=bg, font=font or FF(UI, 9), **kw)
def B(par, text, cmd, fg=TXT, bg=CARD2, hov=LINE, font=None):
    b = tk.Label(par, text=text, fg=fg, bg=bg, font=font or F(UI, 8, "bold"), padx=7, pady=3, cursor="hand2")
    b.bind("<Enter>", lambda e: b.config(bg=hov)); b.bind("<Leave>", lambda e: b.config(bg=bg)); b.bind("<Button-1>", lambda e: cmd()); return b
busy = {"on": False}
def toast(msg, ok=True):
    tl.config(text=msg, fg="white", bg="#11402c" if ok else "#5a1a24"); tl.pack(fill="x", padx=8, pady=(0, 4), before=emerg)
    root.after(7000, lambda: tl.pack_forget() if tl.cget("text") == msg else None)
def confirm(title, lines, fn, danger=True):
    if busy["on"]: toast("Another action is running", False); return
    d = tk.Toplevel(root); d.overrideredirect(True); d.attributes("-topmost", True); d.configure(bg=CARD, highlightthickness=2, highlightbackground=RED if danger else BLU)
    L(d, title, font=F(UI, 11, "bold")).pack(anchor="w", padx=14, pady=(12, 4))
    for ln in lines: L(d, ln, SUB, F(MONO, 9), justify="left").pack(anchor="w", padx=14)
    row = tk.Frame(d, bg=CARD); row.pack(fill="x", padx=14, pady=12)
    def go():
        d.destroy(); busy["on"] = True; toast("Sending…", True)
        def run():
            try: r = fn(); root.after(0, lambda: toast("✓ " + r, not r.startswith("New ")))
            except Exception as e: msg = str(e)[:140]; root.after(0, lambda: toast("✗ " + msg, False))
            finally: busy["on"] = False
        threading.Thread(target=run, daemon=True).start()
    B(row, "Cancel", d.destroy).pack(side="right", padx=(6, 0))
    B(row, "CONFIRM", go, "white", RED if danger else BLU, "#ff3b55" if danger else "#5b9bff").pack(side="right")
    d.update_idletasks(); d.geometry(f"+{root.winfo_x()+20}+{root.winfo_y()+120}"); OWN.add(hwnd_of(d)); d.grab_set(); d.focus_force()  # only ever opened by Kenny's click

# header
hdr = tk.Frame(root, bg=BG); hdr.pack(fill="x", padx=10, pady=(8, 4))
dot = tk.Canvas(hdr, width=10, height=10, bg=BG, highlightthickness=0); dot.pack(side="left"); dotid = dot.create_oval(1, 1, 9, 9, fill=AMB, outline="")
L(hdr, " PROPR", bg=BG, font=F(UI, 10, "bold")).pack(side="left"); live = L(hdr, " CONNECTING", AMB, F(UI, 8, "bold"), BG); live.pack(side="left")
xb = B(hdr, "×", lambda: (open(os.path.join(HERE, "closed_by_user.flag"), "w").write("1"), root.destroy()), DIM, BG, CARD2, F(UI, 11)); xb.pack(side="right")
def rescale(d):
    ns = round(min(1.6, max(0.7, SC["s"] + d)), 2)
    if ns == SC["s"]: return
    if SC["w"]: SC["w"] = round(SC["w"] * ns / SC["s"])
    SC["s"] = ns
    for (fam, size, *st), f in _FONTS.items(): f.configure(size=max(5, round(size * ns)))
    relayout(); save_set(); toast(f"Size {int(ns*100)}%")
B(hdr, "+", lambda: rescale(0.1), SUB, BG, CARD2, F(UI, 10, "bold")).pack(side="right")
B(hdr, "-", lambda: rescale(-0.1), SUB, BG, CARD2, F(UI, 10, "bold")).pack(side="right")
ago = L(hdr, "", DIM, F(UI, 8), BG); ago.pack(side="right", padx=6)
def ds(e): root._d = (e.x_root - root.winfo_x(), e.y_root - root.winfo_y())
def dm(e): root.geometry(f"+{e.x_root-root._d[0]}+{e.y_root-root._d[1]}")
def dr(e):
    try: json.dump({"x": root.winfo_x(), "y": root.winfo_y()}, open(os.path.join(HERE, "pos.json"), "w"))
    except Exception: pass
for w in (hdr, live, ago): w.bind("<Button-1>", ds); w.bind("<B1-Motion>", dm); w.bind("<ButtonRelease-1>", dr)
# equity card
ec = tk.Frame(root, bg=CARD, highlightthickness=1, highlightbackground=CARD); ec.pack(fill="x", padx=8, pady=4)
r1 = tk.Frame(ec, bg=CARD); r1.pack(fill="x", padx=12, pady=(10, 0))
L(r1, "ACCOUNT EQUITY", SUB, F(UI, 8, "bold")).pack(side="left"); L(r1, "qEkueeCybEma", DIM, F(MONO, 8)).pack(side="right")
eql = L(ec, "—", TXT, F(MONO, 24, "bold")); eql.pack(anchor="w", padx=10)
r2 = tk.Frame(ec, bg=CARD); r2.pack(fill="x", padx=12)
pnll = L(r2, "", GRN, F(MONO, 10, "bold")); pnll.pack(side="left"); upl = L(r2, "", GRN, F(MONO, 9)); upl.pack(side="right")
bar = tk.Canvas(ec, height=8, bg=CARD, highlightthickness=0); bar.pack(fill="x", padx=12, pady=(8, 2))
faill = L(ec, "", SUB, F(UI, 7), justify="left"); faill.pack(anchor="w", padx=12, pady=(0, 2))
tbar = tk.Canvas(ec, height=8, bg=CARD, highlightthickness=0); tbar.pack(fill="x", padx=12, pady=(4, 2))
tgl = L(ec, "", SUB, F(UI, 7), justify="left"); tgl.pack(anchor="w", padx=12, pady=(0, 8))
L(root, "POSITIONS", SUB, F(UI, 8, "bold"), BG).pack(anchor="w", padx=12, pady=(6, 2))
posf = tk.Frame(root, bg=BG); posf.pack(fill="x", padx=8)
L(root, "ORDERS", SUB, F(UI, 8, "bold"), BG).pack(anchor="w", padx=12, pady=(8, 2))
ordf = tk.Frame(root, bg=CARD); ordf.pack(fill="x", padx=8)
tl = tk.Label(root, font=F(UI, 9, "bold"), wraplength=WW() - 30, justify="left", padx=8, pady=5)
emerg = B(root, "⚡  EMERGENCY · OPEN TERMINAL", lambda: webbrowser.open(TERM), "white", "#d9304a", "#ff3b55", F(UI, 11, "bold"))
emerg.config(pady=9); emerg.pack(fill="x", padx=8, pady=(10, 4))
L(root, f"mini terminal · reduce-only · v{VERSION}", DIM, F(UI, 7), BG).pack(pady=(0, 6))
# v3.4 drag-to-resize: right edge = width, bottom edge = height, corner grip = both
def relayout():
    w = WW(); tl.config(wraplength=w - 30); faill.config(wraplength=w - 40); tgl.config(wraplength=w - 40)
    rows["sig"] = None   # rebuild rows so they reflow to the new width
    for r in rows["ord"].values(): r["lab"].config(wraplength=w - 60)
    root.geometry(f"{w}x{root.winfo_reqheight() + SC['h']}")
def rs_start(e): root._r = (e.x_root, e.y_root, root.winfo_width(), SC["h"])
def rs_move(e, wx, hy):
    x0, y0, w0, h0 = root._r
    if wx: SC["w"] = int(max(260, min(1200, w0 + e.x_root - x0)))
    if hy: SC["h"] = int(max(0, min(1200, h0 + e.y_root - y0)))
    relayout()
def rs_end(e): save_set()
for cur, wx, hy, place in (("sb_h_double_arrow", 1, 0, dict(relx=1, x=-5, y=0, width=5, relheight=1)),
                            ("sb_v_double_arrow", 0, 1, dict(x=0, rely=1, y=-5, height=5, relwidth=1)),
                            ("bottom_right_corner", 1, 1, dict(relx=1, rely=1, x=-14, y=-14, width=14, height=14))):
    g = tk.Label(root, text="◢" if wx and hy else "", fg=DIM, bg=BG, font=F(UI, 7), cursor=cur)
    g.place(**place); g.bind("<Button-1>", rs_start); g.bind("<B1-Motion>", lambda e, a=wx, b=hy: rs_move(e, a, b)); g.bind("<ButtonRelease-1>", rs_end)
root.geometry(f"{WW()}x1"); root.update_idletasks(); faill.config(wraplength=WW() - 40); tgl.config(wraplength=WW() - 40)
set_noactivate(root); OWN.add(hwnd_of(root))
# Typing in SL/TP boxes needs keyboard focus: allow it only after Kenny clicks a box, drop it again on focus-out.
def _ent_click(e):
    set_noactivate(root, False)
    try: U32.SetForegroundWindow(hwnd_of(root)) if WIN else None
    except Exception: pass
    e.widget.focus_set()
def _ent_leave(e): root.after(50, lambda: set_noactivate(root, True))

rows = {"sig": None, "pos": {}, "ord": {}}
def build():
    for w in posf.winfo_children() + ordf.winfo_children(): w.destroy()
    rows["pos"].clear(); rows["ord"].clear()
    if not D["pos"]: L(posf, "No open positions", DIM, bg=CARD, pady=8).pack(fill="x")
    for p in D["pos"]:
        side = (p.get("positionSide") or "").lower(); sc = GRN if side == "long" else RED
        card = tk.Frame(posf, bg=CARD, highlightthickness=1, highlightbackground=CARD); card.pack(fill="x", pady=3)
        tk.Frame(card, bg=sc, width=4).pack(side="left", fill="y")
        inn = tk.Frame(card, bg=CARD); inn.pack(side="left", fill="x", expand=True, padx=8, pady=6)
        t = tk.Frame(inn, bg=CARD); t.pack(fill="x")
        L(t, p.get("base") or p["asset"], font=F(UI, 11, "bold")).pack(side="left")
        L(t, f" {side.upper()} {p.get('leverage','')}x ", sc, F(UI, 8, "bold"), CARD2).pack(side="left", padx=6)
        pxl = L(t, "", TXT, F(MONO, 10, "bold")); pxl.pack(side="left")
        u = L(t, "", font=F(MONO, 12, "bold")); u.pack(side="right")
        info = L(inn, "", SUB, F(MONO, 8), justify="left", wraplength=WW() - 50); info.pack(anchor="w", pady=(2, 3))
        bd = tk.Frame(inn, bg=CARD); bd.pack(fill="x")
        slb = L(bd, "", font=F(UI, 8, "bold")); slb.pack(side="left"); tpb = L(bd, "", font=F(UI, 8, "bold")); tpb.pack(side="left", padx=5)
        ed = tk.Frame(inn, bg=CARD); ed.pack(fill="x", pady=(5, 0))
        ents = {}
        for kind, lab in (("stop_market", "SL"), ("take_profit_market", "TP")):
            if WW() < 360 and kind == "take_profit_market": ed = tk.Frame(inn, bg=CARD); ed.pack(fill="x", pady=(3, 0))
            L(ed, lab, DIM, F(UI, 8)).pack(side="left")
            e = tk.Entry(ed, width=9, bg=CARD2, fg=TXT, insertbackground=TXT, relief="flat", font=F(MONO, 9), takefocus=0); e.pack(side="left", padx=(3, 2), ipady=2)
            e.bind("<Button-1>", _ent_click, add="+"); e.bind("<FocusOut>", _ent_leave, add="+")
            ex = brackets(p, kind)
            if ex: e.insert(0, ex[0].get("triggerPrice"))
            B(ed, "Set", lambda p=p, k=kind, e=e: ask_set(p, k, e.get()), TXT, BLU if True else CARD2, "#5b9bff").pack(side="left", padx=(0, 8))
            ents[kind] = e
        ac = tk.Frame(inn, bg=CARD); ac.pack(fill="x", pady=(5, 0))
        L(ac, "Close", DIM, F(UI, 8)).pack(side="left", padx=(0, 3))
        for fr in (0.25, 0.5, 0.75):
            B(ac, f"{int(fr*100)}%", lambda p=p, fr=fr: ask_close(p, fr)).pack(side="left", padx=(0, 3))
        B(ac, "100%", lambda p=p: ask_close(p, 1.0), "white", "#7a2230", RED).pack(side="left", padx=(0, 6))
        if WW() < 360: ac = tk.Frame(inn, bg=CARD); ac.pack(fill="x", pady=(4, 0))   # narrow: own line, never clipped
        B(ac, "Stop→Entry", lambda p=p: ask_set(p, "stop_market", p.get("entryPrice"), be=True)).pack(side="left")
        rows["pos"][p["positionId"]] = dict(px=pxl, card=card, u=u, info=info, slb=slb, tpb=tpb)
    if not D["ords"]: L(ordf, "No working orders", DIM, pady=8).pack(fill="x")
    for o in D["ords"]:
        r = tk.Frame(ordf, bg=CARD); r.pack(fill="x", padx=8, pady=2)
        s = (o.get("side") or "").lower(); typ = {"limit": "LIMIT", "stop_market": "STOP", "take_profit_market": "TP", "market": "MKT"}.get(o.get("type"), (o.get("type") or "").upper())
        L(r, o.get("base") or o.get("asset"), font=F(UI, 9, "bold"), anchor="w").pack(side="left")
        L(r, f"{typ} {s.upper()}", GRN if s == "buy" else RED, F(UI, 8, "bold"), anchor="w").pack(side="left", padx=6)
        B(r, "Cancel", lambda o=o: ask_cancel(o), SUB, CARD2, "#5a1a24").pack(side="right")
        r2 = tk.Frame(ordf, bg=CARD); r2.pack(fill="x", padx=8, pady=(0, 3))   # v3.4: price on its own line, wraps instead of clipping
        op = L(r2, "", SUB, F(MONO, 8), justify="left", anchor="w", wraplength=WW() - 60); op.pack(side="left", fill="x")
        rows["ord"][o["orderId"]] = dict(px=op, lab=op, asset=o.get("asset"), txt=f"{qty(o.get('quantity'))} @ {fpx(o.get('price') or o.get('triggerPrice'))}")
def ask_close(p, frac):
    q = q_str(abs(n(p["quantity"])) * frac, p["asset"]); m = mark(p)
    confirm(f"Close {int(frac*100)}%", [f"{p.get('base')} {p['positionSide'].upper()}", f"MARKET {exit_side(p).upper()} {q} (reduce-only)",
            f"≈ price {fpx(m)}  ·  est P&L {upnl(p)*frac:+,.2f}"], lambda: close_part(p, frac))
def ask_set(p, kind, val, be=False):
    try: ps = p_str(n(val, -1), p["asset"])
    except Exception: toast("Enter a valid price", False); return
    m = mark(p); long = p["positionSide"].lower() == "long"
    warn = ""
    if kind == "stop_market" and ((long and float(ps) >= m) or (not long and float(ps) <= m)): warn = "⚠ stop is past the current price - fills immediately"
    if kind == "take_profit_market" and ((long and float(ps) <= m) or (not long and float(ps) >= m)): warn = "⚠ TP is past the current price - fills immediately"
    old = ", ".join(fpx(o.get("triggerPrice")) for o in brackets(p, kind)) or "none"
    lab = "Stop to Entry" if be else ("Set Stop" if kind == "stop_market" else "Set Take-Profit")
    confirm(lab, [f"{p.get('base')} {p['positionSide'].upper()}  qty {q_str(n(p['quantity']), p['asset'])}",
            f"NEW {'STOP' if kind=='stop_market' else 'TP'} {exit_side(p).upper()} @ {ps} (reduce-only)", f"then cancel old: {old}", f"mark now {fpx(m)}"] + ([warn] if warn else []),
            lambda: replace(p, kind, ps), danger=bool(warn))
def ask_cancel(o):
    confirm("Cancel order", [f"{o.get('base') or o.get('asset')} {o.get('type')} {o.get('side')}", f"qty {qty(o.get('quantity'))} @ {fpx(o.get('price') or o.get('triggerPrice'))}",
            ("⚠ this is a protective order" if o.get("reduceOnly") else "")], lambda: (cancel(o["orderId"]), "Order cancelled")[1])

def tick():
    try:
        now = time.time(); fresh = D["mt"] and now - D["mt"] < 10; pl = D["ok"] and now - D["t"] < 20
        c = GRN if fresh and pl else (RED if D["ok"] is False else AMB); dot.itemconfig(dotid, fill=c)
        live.config(text=" LIVE" if fresh and pl else (" RECONNECTING" if D["ok"] is False or (D["mt"] and not fresh) else " CONNECTING"), fg=c)
        ago.config(text=(f"{max(0, int(now - D['mt']))}s ago" if WW() < 340 else f"updated {max(0, int(now - D['mt']))}s ago") if D["mt"] else "waiting")
        a = D["a"]
        if a:
            sig = (tuple(p["positionId"] for p in D["pos"]), tuple((o["orderId"], o.get("triggerPrice"), o.get("price")) for o in D["ords"]))
            if sig != rows["sig"] and not busy["on"] and not (root.focus_get().__class__ is tk.Entry):
                rows["sig"] = sig; build()
            lu = sum(upnl(p) for p in D["pos"]); eq = n(a.get("marginBalance")) - n(a.get("totalUnrealizedPnl")) + lu
            base = day_start(n(a.get("marginBalance"))); pnl = eq - base; pct = pnl / base * 100 if base else 0; room = eq - FAIL
            eql.config(text=f"${eq:,.2f}", fg=RED if room <= 100 else TXT)
            pnll.config(text=f"{'▲' if pnl >= 0 else '▼'} {pnl:+,.2f} ({pct:+.2f}%) today", fg=GRN if pnl >= 0 else RED)
            upl.config(text=f"uPnL {lu:+,.2f}", fg=GRN if lu >= 0 else RED)
            ec.config(highlightbackground=RED if room <= 100 else CARD)
            bar.delete("all"); bw = bar.winfo_width() or WW() - 40; fr = max(0, min(1, room / 500))
            bar.create_rectangle(0, 0, bw, 8, fill=CARD2, outline=""); bar.create_rectangle(0, 0, bw * fr, 8, fill=RED if room <= 100 else AMB if room <= 250 else GRN, outline="")
            faill.config(text=f"Safety: ${room:,.2f} above fail line ${FAIL:,.0f}" + ("   ⚠ DANGER" if room <= 100 else ""), fg=RED if room <= 100 else SUB)
            tbar.delete("all"); tf = max(0, min(1, (eq - 10000) / (TARGET - 10000))) if TARGET > 10000 else 0
            tbar.create_rectangle(0, 0, bw, 8, fill=CARD2, outline=""); tbar.create_rectangle(0, 0, bw * tf, 8, fill=BLU, outline="")
            tgl.config(text=f"Profit target: ${max(0, TARGET - eq):,.2f} to go to ${TARGET:,.0f}  ({tf*100:.0f}%)", fg=BLU if tf >= 1 else SUB)
            for p in D["pos"]:
                r = rows["pos"].get(p["positionId"])
                if not r: continue
                mp = mark(p); r["px"].config(text=f"${fpx(mp)}" if mp else "")
                u = upnl(p); r["u"].config(text=f"{u:+,.2f}", fg=GRN if u >= 0 else RED)
                r["info"].config(text=f"Size {qty(p.get('quantity'))}  Entry {fpx(p.get('entryPrice'))}  Mark {fpx(mark(p))}")
                sl = brackets(p, "stop_market"); tp = brackets(p, "take_profit_market")
                r["slb"].config(text=f" SL {', '.join(fpx(o.get('triggerPrice')) for o in sl)} " if sl else " ⚠ NO STOP ", fg=TXT if sl else "white", bg="#3a1d24" if sl else RED)
                r["tpb"].config(text=f" TP {', '.join(fpx(o.get('triggerPrice')) for o in tp)} " if tp else " NO TP ", fg=TXT if tp else DIM, bg="#123528" if tp else CARD2)
                r["card"].config(highlightbackground=CARD if sl else RED)
            for r in rows["ord"].values():
                mp = n(D["mids"].get(r["asset"])); r["px"].config(text=r["txt"] + (f"   ·   now ${fpx(mp)}" if mp else ""))
        g = f"{WW()}x{root.winfo_reqheight() + SC['h']}"
        if root.geometry().split("+")[0] != g: root.geometry(g)
    except Exception: pass
    root.after(500, tick)
def keep_top():
    try:
        gm = fullscreen_fg()
        if gm:
            if not os.path.exists(GAME): open(GAME, "w").write("1")
        else:
            if os.path.exists(GAME): os.remove(GAME)
            top_noactivate(root)  # SWP_NOACTIVATE: never steals focus
    except Exception: pass
    root.after(3000, keep_top)
for f in (propr_loop, price_loop): threading.Thread(target=f, daemon=True).start()
tick(); keep_top(); root.mainloop()
