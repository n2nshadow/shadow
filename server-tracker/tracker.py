#!/usr/bin/env python3
"""DutyMapper server tracker.

Runs in GitHub Actions (.github/workflows/server-tracker.yml), one run after another:

  1. asks dutymapper.com which servers to watch (GET /api/servers/targets)
  2. asks each server for its status the way the in-game browser does (UDP getstatus + getinfo).
     The website can't do this itself: Cloudflare Workers have no UDP.
  3. posts what it heard to dutymapper.com (POST /api/servers/report), ROUNDS times, GAP seconds apart
  4. redraws a server's banners (banner.py) and uploads them (POST /api/servers/banner) as soon as its
     map, mode or status changes, with new player counts at the end of the run, and at least every
     REFRESH seconds (the day's graph moves on). Each upload costs a storage write, so not every round.

There is no password: every request carries the token GitHub signs for this workflow (OIDC), and
dutymapper.com checks GitHub's signature, the repo and the workflow before it accepts anything.

Local test without posting:  python tracker.py --dry-run
"""
import concurrent.futures
import json
import os
import re
import socket
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SITE = os.environ.get("DUTYMAPPER_URL", "https://dutymapper.com").rstrip("/")
ROUNDS = int(os.environ.get("ROUNDS", "4"))
GAP = int(os.environ.get("GAP", "60"))
REFRESH = int(os.environ.get("REFRESH", "600"))
DRY = "--dry-run" in sys.argv
UA = "dutymapper-server-tracker (+https://github.com/n2nshadow/shadow)"
PLAYER = re.compile(rb'^(-?\d+) (-?\d+) "(.*)"$')


def ask(ip, port, command, timeout=2.5, tries=2):
    """One UDP query; returns (payload lines, round trip ms) or (None, None)."""
    for _ in range(tries):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        try:
            start = time.monotonic()
            s.sendto(b"\xff\xff\xff\xff" + command, (ip, port))
            data, _ = s.recvfrom(65535)
            return data.split(b"\n"), round((time.monotonic() - start) * 1000)
        except OSError:
            continue
        finally:
            s.close()
    return None, None


def cvars(line):
    fields = line.decode("latin-1").split("\\")[1:]
    return dict(zip(fields[0::2], fields[1::2]))


def check(ip, port):
    lines, rtt = ask(ip, port, b"getstatus")
    if not lines or len(lines) < 2:
        return {"ip": ip, "port": port, "online": False}
    info = cvars(lines[1])
    players = []
    for line in lines[2:]:
        m = PLAYER.match(line.strip())
        if m:
            players.append({"score": int(m.group(1)), "ping": int(m.group(2)), "name": m.group(3).decode("latin-1")})
    # getinfo carries the server's own count of real people (CoD4x: g_humanplayers)
    more, _ = ask(ip, port, b"getinfo xxx", tries=1)
    if more and len(more) > 1:
        extra = cvars(more[1])
        if "g_humanplayers" in extra:
            info["g_humanplayers"] = extra["g_humanplayers"]
    return {"ip": ip, "port": port, "online": True, "rtt_ms": rtt, "info": info, "players": players}


_token = {"value": None, "until": 0.0}


def github_token():
    """The workflow's OIDC token, made out to dutymapper.com (reused for a minute: one banner
    drawing is nine uploads)."""
    if _token["value"] and time.time() < _token["until"]:
        return _token["value"]
    url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=" + urllib.parse.quote(SITE, safe="")
    req = urllib.request.Request(url, headers={"Authorization": "bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"], "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        _token["value"] = json.load(r)["value"]
    _token["until"] = time.time() + 60
    return _token["value"]


def call(method, path, body=None, content_type="application/json", signed=False):
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = content_type
    if signed:
        headers["Authorization"] = "Bearer " + github_token()
    req = urllib.request.Request(SITE + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def looks(rep):
    """What a server's banners show: (map, mode, name -- or offline) and (player counts)."""
    if not rep["online"]:
        return "offline", ""
    i = rep["info"]
    return f"{i.get('mapname', '')}|{i.get('g_gametype', '')}|{i.get('sv_hostname', '')}", f"{len(rep['players'])}|{i.get('g_humanplayers', '')}"


def stamp(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 0.0


def draw(addr, sig):
    """Draws every banner for one server from its JSON (which has this round's report in it) and
    uploads them. sig is what they show, so the next run knows whether they need redrawing."""
    import banner  # Pillow is only needed for this part
    try:
        data = json.loads(call("GET", f"/servers/{addr}.json"))
        drawn = banner.draw_all(data, SITE)
    except Exception as err:
        print(f"  banners for {addr} failed:", err, file=sys.stderr)
        return False
    sent = 0
    for kind, png in drawn.items():
        try:
            call("POST", f"/api/servers/banner?server={urllib.parse.quote(addr)}&kind={kind}&sig={urllib.parse.quote(sig)}", png, "image/png", signed=True)
            sent += 1
        except Exception as err:
            print(f"  banner {kind} for {addr} failed:", err, file=sys.stderr)
    print(f"  banners for {addr}: {sent} of {len(drawn)} sent ({data.get('map')}, {data.get('players')} playing)")
    return sent > 0


def main():
    servers = json.loads(call("GET", "/api/servers/targets"))["servers"]
    if not servers:
        print("no servers to check")
        return
    # what each server's banners show right now and when they were drawn, as the site has it
    shown = {f"{s['ip']}:{s['port']}": {"sig": s.get("banner_sig") or "", "at": stamp(s.get("banner_at"))} for s in servers}
    start = time.monotonic()
    for n in range(ROUNDS):
        if n:  # a steady minute apart, however long the drawing took
            time.sleep(max(0.0, start + n * GAP - time.monotonic()))
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            reports = list(pool.map(lambda s: check(s["ip"], int(s["port"])), servers))
        for rep in reports:
            state = f"{len(rep['players'])} connected, {rep['info'].get('mapname')}" if rep["online"] else "no answer"
            print(f"[{n + 1}/{ROUNDS}] {rep['ip']}:{rep['port']}: {state}")
        if DRY:
            print(json.dumps(reports, indent=1)[:3000])
            continue
        # "final": the site writes a server's full state only on a run's last round (or when its map, mode or
        # status changes), to stay inside D1's free 100,000 written rows a day
        body = {"reports": reports, "final": n == ROUNDS - 1}
        try:
            print("  reported:", call("POST", "/api/servers/report", json.dumps(body).encode(), signed=True).decode())
        except Exception as err:  # one failed post shouldn't end the run, but don't draw from old data
            print("  report failed:", err, file=sys.stderr)
            continue
        if os.environ.get("NO_BANNERS") == "1":
            continue
        last = n == ROUNDS - 1
        for rep in reports:
            addr = f"{rep['ip']}:{rep['port']}"
            look, counts = looks(rep)
            sig = f"{look}\n{counts}"
            was = shown.setdefault(addr, {"sig": "", "at": 0.0})
            # a new map, mode or status shows straight away; new player counts at the end of the run;
            # and nothing waits longer than REFRESH
            if look != was["sig"].split("\n")[0] or (last and sig != was["sig"]) or time.time() - was["at"] >= REFRESH:
                if draw(addr, sig):
                    was.update(sig=sig, at=time.time())


if __name__ == "__main__":
    main()
