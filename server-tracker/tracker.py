#!/usr/bin/env python3
"""DutyMapper server tracker.

Runs in GitHub Actions (.github/workflows/server-tracker.yml) every few minutes:

  1. asks dutymapper.com which servers to watch (GET /api/servers/targets)
  2. asks each server for its status the way the in-game browser does (UDP getstatus + getinfo).
     The website can't do this itself: Cloudflare Workers have no UDP.
  3. posts what it heard to dutymapper.com (POST /api/servers/report), ROUNDS times, GAP seconds apart
  4. draws the server banners (banner.py) and uploads them (POST /api/servers/banner)

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

SITE = os.environ.get("DUTYMAPPER_URL", "https://dutymapper.com").rstrip("/")
ROUNDS = int(os.environ.get("ROUNDS", "4"))
GAP = int(os.environ.get("GAP", "60"))
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


def github_token():
    """The workflow's OIDC token, made out to dutymapper.com."""
    url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=" + urllib.parse.quote(SITE, safe="")
    req = urllib.request.Request(url, headers={"Authorization": "bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"], "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)["value"]


def call(method, path, body=None, content_type="application/json", signed=False):
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = content_type
    if signed:
        headers["Authorization"] = "Bearer " + github_token()
    req = urllib.request.Request(SITE + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def main():
    servers = json.loads(call("GET", "/api/servers/targets"))["servers"]
    if not servers:
        print("no servers to check")
        return
    last = {}
    for n in range(ROUNDS):
        if n:
            time.sleep(GAP)
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            reports = list(pool.map(lambda s: check(s["ip"], int(s["port"])), servers))
        for rep in reports:
            last[f"{rep['ip']}:{rep['port']}"] = rep
            state = f"{len(rep['players'])} connected, {rep['info'].get('mapname')}" if rep["online"] else "no answer"
            print(f"[{n + 1}/{ROUNDS}] {rep['ip']}:{rep['port']}: {state}")
        if DRY:
            print(json.dumps(reports, indent=1)[:3000])
            continue
        try:
            print("  reported:", call("POST", "/api/servers/report", json.dumps({"reports": reports}).encode(), signed=True).decode())
        except Exception as err:  # one failed post shouldn't end the run
            print("  report failed:", err, file=sys.stderr)

    if DRY or os.environ.get("NO_BANNERS") == "1":
        return
    import banner  # Pillow is only needed for this part
    for addr in last:
        try:
            data = json.loads(call("GET", f"/servers/{addr}.json"))
            for kind, png in banner.draw_all(data, SITE).items():
                call("POST", f"/api/servers/banner?server={urllib.parse.quote(addr)}&kind={kind}", png, "image/png", signed=True)
                print(f"  banner {kind} for {addr}: {len(png)} bytes")
        except Exception as err:
            print(f"  banner for {addr} failed:", err, file=sys.stderr)


if __name__ == "__main__":
    main()
