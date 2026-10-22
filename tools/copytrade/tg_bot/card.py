"""PnL image cards for practice mode (Pillow). Fake money only."""
import os, tempfile
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1200, 675
BG, PANEL, LINE = (13, 16, 23), (22, 27, 37), (40, 47, 61)
TXT, MUTED, ACCENT = (236, 239, 244), (139, 148, 165), (255, 140, 66)
UP, DOWN, WARN = (34, 214, 128), (255, 84, 102), (255, 196, 61)
INTER = "/usr/share/fonts/truetype/sand-box/google/Inter/Inter-VariableFont_opsz,wght.ttf"
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
MOODS = {"up": "band.png", "down": "sass.png", "flat": "sleep.png", "cry": "cry.png"}  # Gojo the fox; flat = within +/-2%
FLAT_PCT = 2.0
import threading
RENDER = threading.BoundedSemaphore(3)  # Pillow is CPU-heavy: at most 3 cards render at once
DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
DEJAVU_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def font(size, weight="Regular"):
    try:
        f = ImageFont.truetype(INTER, size); f.set_variation_by_name(weight); return f
    except Exception:
        return ImageFont.truetype(DEJAVU_B if weight in ("Bold", "ExtraBold", "SemiBold") else DEJAVU, size)


def money(x): return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"
def signed(x): return ("+" if x >= 0 else "-") + f"${abs(x):,.2f}"
def px_fmt(x):
    if x >= 1: return f"${x:,.2f}"
    if x >= 0.01: return f"${x:.4f}"
    if x <= 0: return "$0"
    import math
    return f"${x:.{min(12, 2 - int(math.floor(math.log10(x))))}f}"


def hold_fmt(sec):
    if sec is None: return "n/a"
    m = int(sec // 60)
    if m < 60: return f"{max(m, 1)} min"
    h, m = divmod(m, 60)
    if h < 48: return f"{h}h {m}m"
    return f"{h // 24}d {h % 24}h"


def _base(real=False):
    im = Image.new("RGBA", (W, H), BG + (255,)); d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 6], fill=ACCENT)
    d.rounded_rectangle([60, 52, 76, 86], 4, fill=ACCENT)
    d.text((92, 46), "Netro Signal", font=font(38, "Bold"), fill=TXT)
    if real:
        d.line([60, 610, W - 60, 610], fill=LINE, width=1)
        d.text((60, 626), "Netro Signal by Netrovert", font=font(20), fill=MUTED)
        return im, d
    tag = "PRACTICE · NOT REAL MONEY"; f = font(20, "Bold"); tw = d.textlength(tag, font=f)
    d.rounded_rectangle([W - 60 - tw - 36, 48, W - 60, 88], 20, fill=(58, 46, 18), outline=WARN, width=2)
    d.text((W - 60 - tw - 18, 57), tag, font=f, fill=WARN)
    d.line([60, 610, W - 60, 610], fill=LINE, width=1)
    d.text((60, 626), "Netro Signal by Netrovert · practice mode, fake money", font=font(20), fill=MUTED)
    return im, d


def mood(pct): return "flat" if abs(pct) <= FLAT_PCT else "up" if pct > 0 else "down"


def _gojo(im, pct):
    """Gojo large on the right, standing on the footer line, with a soft glow in the mood colour."""
    m = pct if isinstance(pct, str) else mood(pct); col = {"up": UP, "down": DOWN, "flat": MUTED, "cry": ACCENT}[m]
    try: g = Image.open(os.path.join(ASSETS, MOODS[m])).convert("RGBA")
    except Exception: return
    g = g.crop(g.getbbox()); bw, bh = 430, 470
    k = min(bw / g.width, bh / g.height); g = g.resize((int(g.width * k), int(g.height * k)), Image.LANCZOS)
    x = W - 40 - g.width + (bw - g.width) // 2 if g.width < bw else W - 40 - g.width; y = 604 - g.height
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0)); gd = ImageDraw.Draw(glow)
    cx, cy = x + g.width // 2, y + g.height // 2 + 30
    gd.ellipse([cx - 230, cy - 200, cx + 230, cy + 200], fill=col + (38,))
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(70)))
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ImageDraw.Draw(sh).ellipse([cx - g.width // 2.6, 590, cx + g.width // 2.6, 616], fill=(0, 0, 0, 120))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)))
    im.alpha_composite(g, (x, y))


def _stat(d, x, y, label, value, w=250):
    d.rounded_rectangle([x, y, x + w, y + 96], 14, fill=PANEL)
    d.text((x + 18, y + 14), label.upper(), font=font(16, "SemiBold"), fill=MUTED)
    size = 30
    while size > 18 and d.textlength(value, font=font(size, "Bold")) > w - 36: size -= 2
    d.text((x + 18, y + 44 + (30 - size) // 2), value, font=font(size, "Bold"), fill=TXT)


def _big_pnl(d, y, pl, pct, maxw=640):
    col = UP if pl >= 0 else DOWN
    size = 112
    while size > 56 and d.textlength(signed(pl), font=font(size, "ExtraBold")) > maxw: size -= 4
    d.text((60, y + (112 - size) // 2), signed(pl), font=font(size, "ExtraBold"), fill=col)
    f = font(40, "Bold"); s = f"{'▲' if pl >= 0 else '▼'} {pct:+.1f}%"
    d.text((60, y + 132), s, font=f, fill=col)


def _save(im, out):
    out = out or tempfile.mktemp(prefix="pnl_", suffix=".png"); im.convert("RGB").save(out, "PNG", optimize=True); return out


def trade_card(t, out=None):
    with RENDER: return _trade_card(t, out)


def _trade_card(t, out=None):
    """t: symbol, chain, entry, exit, pl, pct, hold_sec, open(bool), when"""
    im, d = _base()
    d.text((60, 130), f"${t['symbol']}", font=font(64, "Bold"), fill=TXT)
    sw = d.textlength(f"${t['symbol']}", font=font(64, "Bold"))
    chain = (t.get("chain") or "?").upper(); fc = font(20, "SemiBold"); cw = d.textlength(chain, font=fc)
    d.rounded_rectangle([60 + sw + 24, 156, 60 + sw + 24 + cw + 28, 192], 18, fill=PANEL, outline=LINE)
    d.text((60 + sw + 38, 162), chain, font=fc, fill=MUTED)
    status = "Still open · live price" if t.get("open") else "Closed trade"
    if t.get("source"): status += " · " + t["source"]
    d.text((60, 214), status + (f" · {t['when']}" if t.get("when") else ""), font=font(24), fill=MUTED)
    _gojo(im, t["pct"]); d = ImageDraw.Draw(im)
    _big_pnl(d, 256, t["pl"], t["pct"])
    _stat(d, 60, 476, "Entry", px_fmt(t["entry"]), 230)
    _stat(d, 302, 476, "Now" if t.get("open") else "Exit", px_fmt(t["exit"]), 230)
    _stat(d, 544, 476, "Held", hold_fmt(t.get("hold_sec")), 180)
    return _save(im, out)


def portfolio_card(p, out=None):
    with RENDER: return _portfolio_card(p, out)


def _portfolio_card(p, out=None):
    """p: name, balance, start, pl, pct, wins, losses, best (dict symbol/pl/pct or None), open_count"""
    im, d = _base()
    d.text((60, 130), f"{p.get('name') or 'My'}'s practice run" if p.get("name") else "Practice portfolio", font=font(44, "Bold"), fill=TXT)
    d.text((60, 190), f"Worth {money(p['balance'])} · started with {money(p['start'])}", font=font(26), fill=MUTED)
    _gojo(im, p["pct"]); d = ImageDraw.Draw(im)
    _big_pnl(d, 236, p["pl"], p["pct"])
    b = p.get("best")
    best = f"${b['symbol']} {signed(b['pl'])}" if b else "none yet"
    _stat(d, 60, 452, "Balance", money(p["balance"]), 230)
    _stat(d, 302, 452, "Wins / losses", f"{p['wins']} / {p['losses']}", 170)
    _stat(d, 484, 452, "Best trade", best, 240)
    if p.get("open_count"): d.text((60, 562), f"{p['open_count']} open, valued at live prices", font=font(20), fill=MUTED)
    return _save(im, out)


def fumble_card(f, out=None):
    with RENDER: return _fumble_card(f, out)


def _fumble_card(f, out=None):
    """f: name, total, count, top=[{symbol, sold, peak, missed, x}]"""
    real = bool(f.get("addr")); im, d = _base(real)
    d.text((60, 122), f"{f['addr'][:4]}…{f['addr'][-4:]}'s fumbles" if real else "Fumbled trades", font=font(44, "Bold"), fill=TXT)
    n = f["count"]
    sub = (f"Sold too early {n} time{'s' if n != 1 else ''} in the last 30 days. Real trades, real money." if real
           else f"Sold too early {n} time{'s' if n != 1 else ''}. Here's what holding would have paid.")
    d.text((60, 178), sub, font=font(22), fill=MUTED)
    _gojo(im, "cry" if f["top"] else "up"); d = ImageDraw.Draw(im)
    if not f["top"]:
        d.text((60, 270), "No fumbles!", font=font(96, "ExtraBold"), fill=UP)
        d.text((60, 400), "Nothing you sold went higher after.", font=font(30), fill=TXT)
        return _save(im, out)
    head = f"-${f['total']:,.2f}"; size = 96
    while size > 52 and d.textlength(head, font=font(size, "ExtraBold")) > 620: size -= 4
    d.text((60, 214 + (96 - size) // 2), head, font=font(size, "ExtraBold"), fill=DOWN)
    d.text((60 + d.textlength(head, font=font(size, "ExtraBold")) + 16, 260), "fumbled", font=font(34, "Bold"), fill=ACCENT)
    y = 340
    for c, x in ((60, "TOKEN"), (230, "SOLD AT"), (400, "PEAK AFTER"), (580, "MISSED")):
        d.text((c + 18, y), x, font=font(15, "SemiBold"), fill=MUTED)
    for i, r in enumerate(f["top"][:3]):
        ry = y + 28 + i * 80
        d.rounded_rectangle([60, ry, 740, ry + 68], 12, fill=PANEL)
        sym = "$" + r["symbol"]; fs = 26
        while fs > 16 and d.textlength(sym, font=font(fs, "Bold")) > 150: fs -= 2
        d.text((78, ry + 20 + (26 - fs) // 2), sym, font=font(fs, "Bold"), fill=TXT)
        d.text((248, ry + 22), px_fmt(r["sold"]), font=font(22), fill=MUTED)
        d.text((418, ry + 22), px_fmt(r["peak"]), font=font(22), fill=TXT)
        d.text((598, ry + 10), f"-${r['missed']:,.2f}", font=font(22, "Bold"), fill=DOWN)
        d.text((598, ry + 38), f"{r['x']:.1f}x higher", font=font(16), fill=ACCENT)
    return _save(im, out)
