# DutyMapper server tracker

Live status, banners and a widget for game servers on [dutymapper.com/servers](https://dutymapper.com/servers).

Call of Duty servers only answer their status query over UDP, and the website (Cloudflare Workers)
can't send UDP. So this GitHub Action does the asking:

1. `tracker.py` gets the server list from `https://dutymapper.com/api/servers/targets`.
2. It asks each server for its status (`getstatus` and `getinfo`, the same packets the in-game server
   browser sends), four times, a minute apart.
3. It posts each round to `https://dutymapper.com/api/servers/report`.
4. `banner.py` draws the banners (eight sizes, plus a picture of the website widget for forums) from
   the server's `/servers/<ip>:<port>.json` and uploads them: within a minute when a server's map,
   mode or status changes, with new player counts at the end of each run, and at least every 10
   minutes. Every upload is a storage write, so they aren't redrawn every minute regardless.

Each run of the workflow (`.github/workflows/server-tracker.yml`) takes about 4 minutes, and its
last step starts the next run, so the site hears from every server about once a minute. GitHub's
own schedule only restarts that chain if it ever stops: on its own it runs hours late (on
2026-10-16, about every 4 hours).

To stop the tracker, disable the workflow in the Actions tab. To restart it, open the workflow
there and click "Run workflow".

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

GitHub switches off scheduled workflows in repos that go 60 days without a commit. Every 50 days
the workflow updates `keepalive.txt` to keep itself running.
