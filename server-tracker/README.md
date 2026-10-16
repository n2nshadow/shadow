# DutyMapper server tracker

Live status, banners and a widget for game servers on [dutymapper.com/servers](https://dutymapper.com/servers).

Call of Duty servers only answer their status query over UDP, and the website (Cloudflare Workers)
can't send UDP. So this GitHub Action does the asking:

1. `tracker.py` gets the server list from `https://dutymapper.com/api/servers/targets`.
2. It asks each server for its status (`getstatus` and `getinfo`, the same packets the in-game server
   browser sends), four times, a minute apart.
3. It posts each round to `https://dutymapper.com/api/servers/report`.
4. `banner.py` draws the tall (160×248) and wide (560×95) banners from the server's
   `/servers/<ip>:<port>.json` and uploads them.

The workflow (`.github/workflows/server-tracker.yml`) runs every 5 minutes. GitHub often starts
scheduled runs late, so updates can be 5-15 minutes apart.

## No passwords

Every request to dutymapper.com carries the OIDC token GitHub signs for each run. The site checks
GitHub's signature, and that the token belongs to this repo's `server-tracker.yml` on `master`.
Nothing else can post. There's no secret to set, leak or rotate.

## Servers

Servers are added and removed on dutymapper.com under Admin → Servers. Nothing here needs editing.

## Try it locally

```
python tracker.py --dry-run
```

This asks the servers and prints what it heard, without posting anything.

## Keep-alive

GitHub switches off schedules in repos that go 60 days without a commit. Every 50 days the
workflow updates `keepalive.txt` to keep itself running.
