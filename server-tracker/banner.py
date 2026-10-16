"""Draws a server's DutyMapper banners from /servers/<ip:port>.json.

  tall  160 x 248  -- a sidebar / signature card
  wide  560 x  95  -- a forum-signature strip

Polished rather than a wall of numbers: the map's picture, the server's name, one big player count and a
smooth 24-hour line, in the website's colours and fonts (Big Shoulders Display, Barlow, JetBrains Mono --
the workflow fetches them from Google Fonts' repo; FONTS_DIR points at them, DejaVu stands in if missing).
Everything is drawn at 4x and scaled down, so edges, curves and text come out smooth.
"""
import io
import os
import re
import urllib.request
from datetime import datetime, timezone

from PIL import Image, ImageDraw, ImageFilter, ImageFont

K = 4  # supersampling
BG_TOP, BG_BOTTOM = (31, 32, 26), (19, 20, 16)
BONE, MUTED, FAINT = (240, 234, 218), (168, 163, 142), (104, 101, 86)
AMBER, AMBER_HI = (233, 162, 59), (255, 196, 102)
GREEN, RED, GREY = (110, 222, 120), (232, 96, 80), (150, 146, 128)
UA = "dutymapper-server-tracker (+https://github.com/n2nshadow/shadow)"
FONTS = os.environ.get("FONTS_DIR", "fonts")
FALLBACK = os.environ.get("FONT_FALLBACK", "DejaVuSans.ttf")
_fonts = {}


def font(kind, size):
    """display = Big Shoulders 800, body = Barlow SemiBold, mono = JetBrains Mono 600; size in final pixels."""
    key = (kind, size)
    if key not in _fonts:
        name, weight = {"display": ("BigShouldersDisplay.ttf", 800), "body": ("Barlow-SemiBold.ttf", None),
                        "mono": ("JetBrainsMono.ttf", 600)}[kind]
        try:
            f = ImageFont.truetype(os.path.join(FONTS, name), round(size * K))
            if weight:
                try:
                    f.set_variation_by_axes([weight])
                except Exception:
                    pass
        except OSError:
            f = ImageFont.truetype(FALLBACK, round(size * K))
        _fonts[key] = f
    return _fonts[key]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def picture(url, w, h):
    """Cover-cropped to w x h (final pixels, drawn at K)."""
    try:
        im = Image.open(io.BytesIO(fetch(url))).convert("RGB")
    except Exception:
        return None
    W, H = w * K, h * K
    scale = max(W / im.width, H / im.height)
    im = im.resize((max(W, round(im.width * scale)), max(H, round(im.height * scale))), Image.LANCZOS)
    x, y = (im.width - W) // 2, (im.height - H) // 2
    return im.crop((x, y, x + W, y + H))


def emblem(site, size):
    try:
        return Image.open(io.BytesIO(fetch(site + "/static/art/emblem_96.png"))).convert("RGBA").resize((size * K, size * K), Image.LANCZOS)
    except Exception:
        return None


def plain(raw):
    return re.sub(r"\^\d", "", raw or "").strip()


class Card:
    """A canvas at K times the final size with the few drawing tools the banners need."""

    def __init__(self, w, h, radius):
        self.w, self.h, self.r = w, h, radius
        self.im = Image.new("RGBA", (w * K, h * K), (0, 0, 0, 0))
        # background: a soft vertical gradient
        grad = Image.new("RGB", (1, h * K))
        for y in range(h * K):
            t = y / (h * K - 1)
            grad.putpixel((0, y), tuple(round(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)))
        self.im.paste(grad.resize((w * K, h * K)), (0, 0))
        self.d = ImageDraw.Draw(self.im)

    def text(self, x, y, s, kind, size, fill, anchor="la", tracking=0):
        f = font(kind, size)
        if not tracking:
            self.d.text((x * K, y * K), s, font=f, fill=fill, anchor=anchor)
            return self.d.textlength(s, font=f) / K
        # letter-spaced (labels): draw character by character
        total = sum(self.d.textlength(c, font=f) for c in s) + tracking * K * (len(s) - 1)
        cx = x * K - (total if anchor[0] == "r" else total / 2 if anchor[0] == "m" else 0)
        for c in s:
            self.d.text((cx, y * K), c, font=f, fill=fill, anchor="l" + anchor[1])
            cx += self.d.textlength(c, font=f) + tracking * K
        return total / K

    def width(self, s, kind, size, tracking=0):
        f = font(kind, size)
        return (self.d.textlength(s, font=f) + tracking * K * max(0, len(s) - 1)) / K

    def paste(self, img, x, y, mask=None):
        self.im.paste(img, (round(x * K), round(y * K)), mask if mask is not None else (img if img.mode == "RGBA" else None))

    def paste_fading(self, img, x, y, fade_from, horizontal=False):
        """Pastes a picture that dissolves into the card from `fade_from` (0-1 along its height, or
        width) to its far edge, so there is no seam where it ends."""
        w, h = img.size
        n = w if horizontal else h
        ramp = Image.new("L", (n, 1) if horizontal else (1, n))
        for i in range(n):
            t = max(0.0, (i / (n - 1) - fade_from) / (1 - fade_from))
            t = t * t * (3 - 2 * t)
            ramp.putpixel((i, 0) if horizontal else (0, i), round(255 * (1 - t)))
        self.im.paste(img, (round(x * K), round(y * K)), ramp.resize((w, h)))

    def chip(self, x, y, w, h):
        """A small dark glass square, for the logo on top of a picture."""
        glass = Image.new("RGBA", self.im.size, (0, 0, 0, 0))
        ImageDraw.Draw(glass).rounded_rectangle((x * K, y * K, (x + w) * K, (y + h) * K), radius=4 * K, fill=(10, 10, 8, 165), outline=(255, 255, 255, 34), width=K)
        self.im.alpha_composite(glass)

    def fade(self, x, y, w, h, start, end, colour, horizontal=False):
        """Fades a region into `colour`: alpha goes from start (0-255) to end along the region."""
        n = (w if horizontal else h) * K
        ramp = Image.new("L", (n, 1) if horizontal else (1, n))
        for i in range(n):
            t = i / max(1, n - 1)
            t = t * t * (3 - 2 * t)  # smoothstep
            ramp.putpixel((i, 0) if horizontal else (0, i), round(start + (end - start) * t))
        layer = Image.new("RGBA", (w * K, h * K), colour + (255,))
        layer.putalpha(ramp.resize((w * K, h * K)))
        self.im.alpha_composite(layer, (round(x * K), round(y * K)))

    def pill(self, x, y, label, colour, live):
        """The status chip: dark glass, a glowing dot, letter-spaced label."""
        tw = self.width(label, "body", 7.5, tracking=1.1)
        w, h = tw + 19, 13
        glass = Image.new("RGBA", self.im.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glass)
        gd.rounded_rectangle(((x) * K, y * K, (x + w) * K, (y + h) * K), radius=h / 2 * K, fill=(10, 10, 8, 175), outline=(255, 255, 255, 38), width=K)
        if live:  # glow
            glow = Image.new("RGBA", self.im.size, (0, 0, 0, 0))
            ImageDraw.Draw(glow).ellipse(((x + 4) * K, (y + 3.5) * K, (x + 10) * K, (y + 9.5) * K), fill=colour + (200,))
            glass.alpha_composite(glow.filter(ImageFilter.GaussianBlur(3 * K)))
        gd.ellipse(((x + 5) * K, (y + 4.5) * K, (x + 9) * K, (y + 8.5) * K), fill=colour + (255,))
        self.im.alpha_composite(glass)
        self.text(x + 13, y + h / 2 + 0.3, label, "body", 7.5, BONE, anchor="lm", tracking=1.1)
        return w

    def sparkline(self, box, history, live):
        """A smooth line of people playing over 24 h, with a soft amber fill underneath."""
        x0, y0, x1, y1 = box
        bins = 48
        now = datetime.now(timezone.utc).timestamp()
        vals = [None] * bins
        for at, humans, bots in history:
            try:
                t = datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            except ValueError:
                continue
            i = int((t - (now - 86400)) // (86400 / bins))
            if 0 <= i < bins:
                v = humans if humans is not None else 0
                vals[i] = v if vals[i] is None else max(vals[i], v)
        if all(v is None for v in vals):
            self.text((x0 + x1) / 2, (y0 + y1) / 2, "NO HISTORY YET", "body", 6.5, FAINT, anchor="mm", tracking=1)
            return
        top = max(3, max(v for v in vals if v is not None))
        pts = []
        for i, v in enumerate(vals):
            if v is None:
                continue
            pts.append((x0 + (x1 - x0) * i / (bins - 1), y1 - 1.5 - (y1 - y0 - 3) * v / top))
        # Catmull-Rom through the points for a smooth curve
        curve = []
        for i in range(len(pts) - 1):
            p0, p1, p2, p3 = pts[max(0, i - 1)], pts[i], pts[i + 1], pts[min(len(pts) - 1, i + 2)]
            for s in range(8):
                t = s / 8
                t2, t3 = t * t, t * t * t
                curve.append(tuple(0.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2 + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3) for k in (0, 1)))
        curve.append(pts[-1])
        curve = [(cx, min(y1 - 0.5, max(y0, cy))) for cx, cy in curve]
        # fill: amber fading down to nothing, masked to the area under the curve
        mask = Image.new("L", self.im.size, 0)
        ImageDraw.Draw(mask).polygon([(curve[0][0] * K, y1 * K)] + [(cx * K, cy * K) for cx, cy in curve] + [(curve[-1][0] * K, y1 * K)], fill=255)
        fill = Image.new("RGBA", self.im.size, AMBER + (0,))
        ramp = Image.new("L", (1, (y1 - y0) * K))
        for i in range((y1 - y0) * K):
            ramp.putpixel((0, i), round(110 * (1 - i / ((y1 - y0) * K)) ** 1.4))
        alpha = Image.new("L", self.im.size, 0)
        alpha.paste(ramp.resize(((x1 - x0) * K, (y1 - y0) * K)), (x0 * K, y0 * K))
        fill.putalpha(Image.composite(alpha, Image.new("L", self.im.size, 0), mask))
        self.im.alpha_composite(fill)
        self.d.line([(cx * K, cy * K) for cx, cy in curve], fill=AMBER + (255,), width=round(1.6 * K), joint="curve")
        if live:  # the latest point, lit
            ex, ey = curve[-1]
            glow = Image.new("RGBA", self.im.size, (0, 0, 0, 0))
            ImageDraw.Draw(glow).ellipse(((ex - 3) * K, (ey - 3) * K, (ex + 3) * K, (ey + 3) * K), fill=AMBER_HI + (190,))
            self.im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(2 * K)))
            self.d.ellipse(((ex - 1.6) * K, (ey - 1.6) * K, (ex + 1.6) * K, (ey + 1.6) * K), fill=AMBER_HI + (255,))

    def finish(self):
        """Rounds the corners, adds a hairline edge, and scales down to the real size."""
        mask = Image.new("L", self.im.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, self.w * K - 1, self.h * K - 1), radius=self.r * K, fill=255)
        edge = Image.new("RGBA", self.im.size, (0, 0, 0, 0))
        ImageDraw.Draw(edge).rounded_rectangle((0, 0, self.w * K - 1, self.h * K - 1), radius=self.r * K, outline=(255, 255, 255, 34), width=K)
        self.im.alpha_composite(edge)
        out = Image.new("RGBA", self.im.size, (0, 0, 0, 0))
        out.paste(self.im, (0, 0), mask)
        return out.resize((self.w, self.h), Image.LANCZOS)


def status(data):
    s = data.get("status")
    return ("LIVE", GREEN, True) if s == "online" else ("OFFLINE", RED, False) if s == "offline" else ("NO DATA", GREY, False)


def fit(card, text, kind, sizes, width, lines=1):
    """Largest size at which text fits in `lines` lines of `width`; returns (size, [lines])."""
    words = text.split()
    for size in sizes:
        out, cur = [], ""
        for w in words:
            trial = f"{cur} {w}".strip()
            if cur and card.width(trial, kind, size) > width:
                out.append(cur)
                cur = w
            else:
                cur = trial
        if cur:
            out.append(cur)
        if len(out) <= lines and all(card.width(l, kind, size) <= width for l in out):
            return size, out
    size = sizes[-1]
    s = text
    while s and card.width(s + "…", kind, size) > width:
        s = s[:-1]
    return size, [s + "…" if s != text else s]


def tall(data, site):
    W, H = 160, 248
    c = Card(W, H, 12)
    name = plain(data.get("hostname") or data.get("name") or "").upper()
    label, colour, live = status(data)
    # the map's whole picture across the top (cards are 16:10 and often carry their own title, so
    # nothing is cropped), dissolving into the card
    pic = picture(data.get("map_image") or site + "/static/art/servers_bunker.jpg", W, 100)
    if pic:
        c.paste_fading(pic, 0, 0, 0.42)
    c.fade(0, 0, W, 30, 110, 0, (8, 8, 6))           # a little darker under the pill
    # top right: map cards usually carry their title at the top left
    c.pill(W - 9 - (c.width(label, "body", 7.5, tracking=1.1) + 19), 9, label, colour, live)
    # name, over the fade
    size, lines = fit(c, name, "display", [24, 22, 20, 18, 16, 14], W - 20, 2)
    y = 116 - (len(lines) - 1) * size * 0.92
    for ln in lines:
        c.text(10, y, ln, "display", size, BONE, anchor="ls")
        y += size * 0.92
    # map and mode
    mp = data.get("map_name") or data.get("map") or ""
    gt = data.get("gametype_name") or ""
    _, mline = fit(c, f"{mp}  ·  {gt}" if gt else mp, "body", [9], W - 20, 1)
    c.text(10, 123, mline[0], "body", 9, MUTED)
    # the one number that matters
    if live:
        num = str(data.get("players", 0))
        nw = c.text(10, 172, num, "display", 42, AMBER, anchor="ls")
        c.text(10 + nw + 6, 157, f"of {data.get('max_players', 0)} playing", "body", 9, BONE)
        if data.get("bots"):
            c.text(10 + nw + 6, 169, f"+{data['bots']} bots", "body", 8, MUTED)
    else:
        c.text(10, 170, "Offline" if label == "OFFLINE" else "No data yet", "display", 26, MUTED, anchor="ls")
    # the last 24 hours
    c.text(10, 185, "LAST 24 HOURS", "body", 6.5, FAINT, tracking=1.2)
    c.sparkline((10, 195, W - 10, 222), data.get("history") or [], live)
    # footer: address and where it's from
    c.d.line((10 * K, 230 * K, (W - 10) * K, 230 * K), fill=(255, 255, 255, 22), width=K)
    c.text(10, 240, data.get("address", ""), "mono", 7.5, BONE, anchor="lm")
    c.text(W - 10, 240, "DUTYMAPPER", "display", 9, AMBER, anchor="rm", tracking=0.6)
    return c.finish()


def wide(data, site):
    W, H = 560, 95
    c = Card(W, H, 12)
    name = plain(data.get("hostname") or data.get("name") or "").upper()
    label, colour, live = status(data)
    # the map's whole picture on the left (16:10 at full height), dissolving into the card
    pw = 152
    pic = picture(data.get("map_image") or site + "/static/art/servers_bunker.jpg", pw, H)
    if pic:
        c.paste_fading(pic, 0, 0, 0.5, horizontal=True)
    c.pill(9, H - 22, label, colour, live)
    # name and details
    x = 166
    size, lines = fit(c, name, "display", [30, 28, 26, 24, 22, 20, 18], 230, 1)
    c.text(x, 42, lines[0], "display", size, BONE, anchor="ls")
    mp = data.get("map_name") or data.get("map") or ""
    gt = data.get("gametype_name") or ""
    _, mline = fit(c, f"{mp}  ·  {gt}" if gt else mp, "body", [11], 230, 1)
    c.text(x, 50, mline[0], "body", 11, MUTED)
    c.text(x, 76, data.get("address", ""), "mono", 9.5, BONE, anchor="lm")
    aw = c.width(data.get("address", ""), "mono", 9.5)
    c.text(x + aw + 10, 76, "DUTYMAPPER.COM", "body", 7, FAINT, anchor="lm", tracking=1.2)
    # the count and the day
    rx = 418
    c.d.line(((rx - 14) * K, 14 * K, (rx - 14) * K, (H - 14) * K), fill=(255, 255, 255, 22), width=K)
    if live:
        num = str(data.get("players", 0))
        nw = c.text(rx, 46, num, "display", 38, AMBER, anchor="ls")
        c.text(rx + nw + 6, 30, f"of {data.get('max_players', 0)} playing", "body", 9.5, BONE)
        if data.get("bots"):
            c.text(rx + nw + 6, 42, f"+{data['bots']} bots", "body", 8.5, MUTED)
    else:
        c.text(rx, 44, "Offline" if label == "OFFLINE" else "No data yet", "display", 26, MUTED, anchor="ls")
    c.text(rx, 56, "LAST 24 HOURS", "body", 6.5, FAINT, tracking=1.2)
    c.sparkline((rx, 67, W - 14, 85), data.get("history") or [], live)
    return c.finish()


def clip(c, s, kind, size, width):
    if c.width(s, kind, size) <= width:
        return s
    while s and c.width(s + "…", kind, size) > width:
        s = s[:-1]
    return s.rstrip() + "…"


def player_list(c, data, x, y, width, rows, columns=1, gap=10, row_h=14):
    """Who's on: people first by score, then bots (dimmed); '+N more' when they don't all fit."""
    players = data.get("online_players") or []
    people = [p for p in players if not p.get("bot")]
    bots = [p for p in players if p.get("bot")]
    ordered = people + bots
    cap = rows * columns
    more = len(ordered) - cap
    shown = ordered[: cap - 1] if more > 0 else ordered[:cap]
    colw = (width - gap * (columns - 1)) / columns
    if not ordered:
        msg = "Nobody's on right now." if data.get("status") == "online" else "Not answering." if data.get("status") == "offline" else "No data yet."
        c.text(x, y + row_h / 2, msg, "body", 8.5, FAINT, anchor="lm")
        return
    for i, p in enumerate(shown + ([None] if more > 0 else [])):
        col, row = divmod(i, rows)
        px, py = x + col * (colw + gap), y + row * row_h
        if row % 2 == 0:
            band = Image.new("RGBA", c.im.size, (0, 0, 0, 0))
            ImageDraw.Draw(band).rounded_rectangle((px * K, py * K, (px + colw) * K, (py + row_h - 1) * K), radius=3 * K, fill=(255, 255, 255, 9))
            c.im.alpha_composite(band)
        if p is None:
            c.text(px + 6, py + row_h / 2, f"+{more + 1} more", "body", 8, MUTED, anchor="lm")
            continue
        bot = p.get("bot")
        score = str(p.get("score", 0))
        sw = c.width(score, "mono", 7.5)
        tag = "BOT" if bot else ""
        tw = c.width(tag, "body", 6, tracking=0.8) + 6 if tag else 0
        raw = re.sub(r"^\[bot\]\s*", "", p.get("name") or "?", flags=re.I) if bot else (p.get("name") or "?")
        name = clip(c, raw or "?", "body", 8.5, colw - 18 - sw - tw)
        nw = c.text(px + 6, py + row_h / 2, name, "body", 8.5, FAINT if bot else BONE, anchor="lm")
        if tag:
            c.text(px + 6 + nw + 5, py + row_h / 2 + 0.3, tag, "body", 6, FAINT, anchor="lm", tracking=0.8)
        c.text(px + colw - 6, py + row_h / 2, score, "mono", 7.5, FAINT if bot else MUTED, anchor="rm")


def count_block(c, data, x, baseline, live, label, size=44):
    if live:
        num = str(data.get("players", 0))
        nw = c.text(x, baseline, num, "display", size, AMBER, anchor="ls")
        c.text(x + nw + 7, baseline - size * 0.36, f"of {data.get('max_players', 0)} playing", "body", 9.5, BONE)
        if data.get("bots"):
            c.text(x + nw + 7, baseline - size * 0.36 + 13, f"+{data['bots']} bots", "body", 8.5, MUTED)
    else:
        c.text(x, baseline - 2, "Offline" if label == "OFFLINE" else "No data yet", "display", 28, MUTED, anchor="ls")


def large(data, site):
    """560 x 250: the wide strip made taller, with everyone who's on listed."""
    W, H = 560, 250
    c = Card(W, H, 14)
    name = plain(data.get("hostname") or data.get("name") or "").upper()
    label, colour, live = status(data)
    lw = 222
    pic = picture(data.get("map_image") or site + "/static/art/servers_bunker.jpg", lw, round(lw / 1.6))
    if pic:
        c.paste_fading(pic, 0, 0, 0.5)
    c.fade(0, 0, lw, 30, 110, 0, (8, 8, 6))
    c.pill(lw - 9 - (c.width(label, "body", 7.5, tracking=1.1) + 19), 9, label, colour, live)
    count_block(c, data, 14, 186, live, label, 46)
    c.text(14, 200, "LAST 24 HOURS", "body", 6.5, FAINT, tracking=1.2)
    c.sparkline((14, 209, lw - 12, 236), data.get("history") or [], live)
    c.d.line((lw * K, 16 * K, lw * K, (H - 16) * K), fill=(255, 255, 255, 20), width=K)
    # right: who, where, and who's on
    x = lw + 16
    size, lines = fit(c, name, "display", [30, 28, 26, 24, 22, 20, 18], W - x - 14, 2)
    y = 40
    for ln in lines:
        c.text(x, y, ln, "display", size, BONE, anchor="ls")
        y += size * 0.92
    mp = data.get("map_name") or data.get("map") or ""
    gt = data.get("gametype_name") or ""
    _, mline = fit(c, f"{mp}  ·  {gt}" if gt else mp, "body", [11], W - x - 14, 1)
    y = y - size * 0.92 + 9
    c.text(x, y, mline[0], "body", 11, MUTED)
    c.text(x, y + 22, data.get("address", ""), "mono", 9.5, BONE, anchor="lm")
    c.text(W - 14, y + 22, "DUTYMAPPER", "display", 10, AMBER, anchor="rm", tracking=0.6)
    ly = y + 38
    n = len(data.get("online_players") or [])
    c.text(x, ly, f"ONLINE NOW · {n}" if live else "ONLINE NOW", "body", 6.5, FAINT, tracking=1.2)
    rows = max(3, int((H - 14 - (ly + 9)) // 14))
    player_list(c, data, x - 2, ly + 9, W - x - 12, rows, columns=2)
    return c.finish()


def sidebar(data, site):
    """240 x 440: the tall card made bigger, with the player list underneath."""
    W, H = 240, 440
    c = Card(W, H, 14)
    name = plain(data.get("hostname") or data.get("name") or "").upper()
    label, colour, live = status(data)
    pic = picture(data.get("map_image") or site + "/static/art/servers_bunker.jpg", W, 150)
    if pic:
        c.paste_fading(pic, 0, 0, 0.42)
    c.fade(0, 0, W, 30, 110, 0, (8, 8, 6))
    c.pill(W - 10 - (c.width(label, "body", 7.5, tracking=1.1) + 19), 10, label, colour, live)
    size, lines = fit(c, name, "display", [30, 28, 26, 24, 22, 20, 18], W - 24, 2)
    y = 150 - (len(lines) - 1) * size * 0.92
    for ln in lines:
        c.text(12, y, ln, "display", size, BONE, anchor="ls")
        y += size * 0.92
    mp = data.get("map_name") or data.get("map") or ""
    gt = data.get("gametype_name") or ""
    _, mline = fit(c, f"{mp}  ·  {gt}" if gt else mp, "body", [10], W - 24, 1)
    c.text(12, 158, mline[0], "body", 10, MUTED)
    count_block(c, data, 12, 216, live, label, 46)
    c.text(12, 230, "LAST 24 HOURS", "body", 6.5, FAINT, tracking=1.2)
    c.sparkline((12, 240, W - 12, 268), data.get("history") or [], live)
    n = len(data.get("online_players") or [])
    c.text(12, 284, f"ONLINE NOW · {n}" if live else "ONLINE NOW", "body", 6.5, FAINT, tracking=1.2)
    player_list(c, data, 10, 293, W - 20, 8)
    c.d.line((12 * K, (H - 24) * K, (W - 12) * K, (H - 24) * K), fill=(255, 255, 255, 22), width=K)
    c.text(12, H - 12, data.get("address", ""), "mono", 8.5, BONE, anchor="lm")
    c.text(W - 12, H - 12, "DUTYMAPPER", "display", 10, AMBER, anchor="rm", tracking=0.6)
    return c.finish()


def glow_dot(c, x, y, r, colour, live):
    if live:
        g = Image.new("RGBA", c.im.size, (0, 0, 0, 0))
        ImageDraw.Draw(g).ellipse(((x - r * 2) * K, (y - r * 2) * K, (x + r * 2) * K, (y + r * 2) * K), fill=colour + (170,))
        c.im.alpha_composite(g.filter(ImageFilter.GaussianBlur(r * K)))
    c.d.ellipse(((x - r) * K, (y - r) * K, (x + r) * K, (y + r) * K), fill=colour + (255,))


def micro(data, site):
    """350 x 20: one line -- status, name, map, players."""
    W, H = 350, 20
    c = Card(W, H, 5)
    label, colour, live = status(data)
    glow_dot(c, 9, H / 2, 2.6, colour, live)
    count = f"{data.get('players', 0)}/{data.get('max_players', 0)}" if live else ("OFF" if label == "OFFLINE" else "—")
    cw = c.width(count, "display", 13)
    c.text(W - 8, H / 2 + 0.5, count, "display", 13, AMBER if live else MUTED, anchor="rm")
    name = clip(c, plain(data.get("hostname") or data.get("name") or "").upper(), "display", 12.5, 170)
    nw = c.text(17, H / 2 + 0.5, name, "display", 12.5, BONE, anchor="lm")
    mp = clip(c, data.get("map_name") or data.get("map") or "", "body", 8.5, W - 8 - cw - 10 - (17 + nw + 12))
    c.text(W - 8 - cw - 9, H / 2 + 0.5, mp, "body", 8.5, MUTED, anchor="rm")
    return c.finish()


def small(data, site):
    """468 x 60: picture, name, map, address, count and a little graph."""
    W, H = 468, 60
    c = Card(W, H, 9)
    label, colour, live = status(data)
    pw = 96
    pic = picture(data.get("map_image") or site + "/static/art/servers_bunker.jpg", pw, H)
    if pic:
        c.paste_fading(pic, 0, 0, 0.45, horizontal=True)
    x = 104
    name = plain(data.get("hostname") or data.get("name") or "").upper()
    size, lines = fit(c, name, "display", [21, 20, 19, 18, 17, 16, 15, 14], 228, 1)
    c.text(x, 25, lines[0], "display", size, BONE, anchor="ls")
    mp = data.get("map_name") or data.get("map") or ""
    gt = data.get("gametype_name") or ""
    c.text(x, 31, clip(c, f"{mp}  ·  {gt}" if gt else mp, "body", 9, 228), "body", 9, MUTED)
    glow_dot(c, x + 3, 50, 2.3, colour, live)
    c.text(x + 10, 50, data.get("address", ""), "mono", 7.5, BONE, anchor="lm")
    rx = 350
    c.d.line(((rx - 12) * K, 10 * K, (rx - 12) * K, (H - 10) * K), fill=(255, 255, 255, 20), width=K)
    if live:
        num = str(data.get("players", 0))
        nw = c.text(rx, 30, num, "display", 26, AMBER, anchor="ls")
        c.text(rx + nw + 5, 15, f"of {data.get('max_players', 0)}", "body", 8.5, BONE)
        c.text(rx + nw + 5, 25, "playing", "body", 7.5, MUTED)
    else:
        c.text(rx, 28, "Offline" if label == "OFFLINE" else "No data", "display", 18, MUTED, anchor="ls")
    c.sparkline((rx, 36, W - 10, 52), data.get("history") or [], live)
    return c.finish()


def square(data, site):
    """250 x 250: picture, name, count and the day."""
    W, H = 250, 250
    c = Card(W, H, 14)
    name = plain(data.get("hostname") or data.get("name") or "").upper()
    label, colour, live = status(data)
    pic = picture(data.get("map_image") or site + "/static/art/servers_bunker.jpg", W, 156)
    if pic:
        c.paste_fading(pic, 0, 0, 0.42)
    c.fade(0, 0, W, 30, 110, 0, (8, 8, 6))
    c.pill(W - 10 - (c.width(label, "body", 7.5, tracking=1.1) + 19), 10, label, colour, live)
    size, lines = fit(c, name, "display", [28, 26, 24, 22, 20, 18, 16], W - 24, 2)
    y = 132 - (len(lines) - 1) * size * 0.92
    for ln in lines:
        c.text(12, y, ln, "display", size, BONE, anchor="ls")
        y += size * 0.92
    mp = data.get("map_name") or data.get("map") or ""
    gt = data.get("gametype_name") or ""
    c.text(12, 140, clip(c, f"{mp}  ·  {gt}" if gt else mp, "body", 9.5, W - 24), "body", 9.5, MUTED)
    count_block(c, data, 12, 194, live, label, 40)
    c.sparkline((12, 202, W - 12, 226), data.get("history") or [], live)
    c.d.line((12 * K, 233 * K, (W - 12) * K, 233 * K), fill=(255, 255, 255, 22), width=K)
    c.text(12, 242, data.get("address", ""), "mono", 7.5, BONE, anchor="lm")
    c.text(W - 12, 242, "DUTYMAPPER", "display", 9, AMBER, anchor="rm", tracking=0.6)
    return c.finish()


def top_list(c, data, x, y, width, rows, row_h=14):
    """Most points earned since tracking began (people only)."""
    top = (data.get("top_players") or [])[:rows]
    if not top:
        c.text(x, y + row_h / 2, "Nobody recorded yet.", "body", 8.5, FAINT, anchor="lm")
        return
    for i, p in enumerate(top):
        py = y + i * row_h
        if i % 2 == 0:
            band = Image.new("RGBA", c.im.size, (0, 0, 0, 0))
            ImageDraw.Draw(band).rounded_rectangle((x * K, py * K, (x + width) * K, (py + row_h - 1) * K), radius=3 * K, fill=(255, 255, 255, 9))
            c.im.alpha_composite(band)
        c.text(x + 6, py + row_h / 2, str(i + 1), "mono", 7.5, AMBER if i < 3 else FAINT, anchor="lm")
        score = f"{p.get('score', 0):,}"
        hrs = (p.get("seconds") or 0) / 3600
        when = f"{hrs:.0f}h" if hrs >= 1 else f"{max(1, round(hrs * 60))}m"
        sw = c.width(score, "mono", 7.5)
        c.text(x + width - 6, py + row_h / 2, score, "mono", 7.5, MUTED, anchor="rm")
        c.text(x + width - 12 - sw, py + row_h / 2, when, "body", 7, FAINT, anchor="rm")
        ww = c.width(when, "body", 7)
        c.text(x + 20, py + row_h / 2, clip(c, p.get("name") or "?", "body", 8.5, width - 38 - sw - ww), "body", 8.5, BONE, anchor="lm")


def showcase(data, site):
    """760 x 340: everything -- picture, count, a bigger day graph, who's on and the top players."""
    W, H = 760, 340
    c = Card(W, H, 16)
    name = plain(data.get("hostname") or data.get("name") or "").upper()
    label, colour, live = status(data)
    lw = 300
    pic = picture(data.get("map_image") or site + "/static/art/servers_bunker.jpg", lw, round(lw / 1.6))
    if pic:
        c.paste_fading(pic, 0, 0, 0.5)
    c.fade(0, 0, lw, 32, 110, 0, (8, 8, 6))
    c.pill(lw - 11 - (c.width(label, "body", 7.5, tracking=1.1) + 19), 11, label, colour, live)
    count_block(c, data, 16, 236, live, label, 56)
    c.text(16, 256, "LAST 24 HOURS", "body", 6.5, FAINT, tracking=1.2)
    if data.get("peak_24h"):
        c.text(lw - 14, 256, f"PEAK {data['peak_24h']}", "body", 6.5, FAINT, anchor="ra", tracking=1.2)
    c.sparkline((16, 266, lw - 14, 322), data.get("history") or [], live)
    c.d.line((lw * K, 18 * K, lw * K, (H - 18) * K), fill=(255, 255, 255, 20), width=K)
    x = lw + 18
    size, lines = fit(c, name, "display", [38, 36, 34, 32, 30, 28, 26, 24], W - x - 18, 1)
    c.text(x, 50, lines[0], "display", size, BONE, anchor="ls")
    mp = data.get("map_name") or data.get("map") or ""
    gt = data.get("gametype_name") or ""
    c.text(x, 59, clip(c, f"{mp}  ·  {gt}" if gt else mp, "body", 12, W - x - 18), "body", 12, MUTED)
    c.text(x, 90, data.get("address", ""), "mono", 10, BONE, anchor="lm")
    c.text(W - 18, 90, "DUTYMAPPER.COM", "display", 11, AMBER, anchor="rm", tracking=0.8)
    c.d.line((x * K, 104 * K, (W - 18) * K, 104 * K), fill=(255, 255, 255, 20), width=K)
    colw = (W - x - 18 - 16) / 2
    n = len(data.get("online_players") or [])
    c.text(x, 116, f"ONLINE NOW · {n}" if live else "ONLINE NOW", "body", 6.5, FAINT, tracking=1.2)
    player_list(c, data, x - 2, 126, colw + 2, 14)
    tx = x + colw + 16
    c.text(tx, 116, "TOP PLAYERS", "body", 6.5, FAINT, tracking=1.2)
    top_list(c, data, tx - 2, 126, colw + 2, 14)
    return c.finish()


KINDS = {"micro": micro, "small": small, "tall": tall, "square": square, "wide": wide,
         "sidebar": sidebar, "large": large, "showcase": showcase}


def draw_all(data, site):
    out = {}
    for kind, fn in KINDS.items():
        buf = io.BytesIO()
        fn(data, site).save(buf, "PNG", optimize=True)
        out[kind] = buf.getvalue()
    return out
