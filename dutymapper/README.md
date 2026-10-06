# DutyMapper: show admins who downloaded which maps

Today `download()` only bumps `game_maps.downloads` and `game_downloads_daily`. Neither stores who
downloaded, so **there's no history to show for downloads made before this change**. The log
starts filling once this is deployed.

This adds:
- a `map_downloads` table (one row per member download)
- an **Admin → Downloads** page at `/admin/downloads` that lists member, map and time, newest first.
  You can search by member and/or map, and each row links to "all their downloads" and
  "everyone who got it". Only full admins can see it, the same as Messages.

## 1. Create the table (before deploying the code)

```sh
npx wrangler d1 execute dutymapper --remote --file=migrations/map_downloads.sql
```

## 2. New file

Copy `src/admin_downloads.js` into the worker's `src/`. The imports assume `esc/page/notFound/fmtNum/timeTag`
are exported from `views.js`, `USER_COLUMNS/adminNav/avatarHtml/nameHtml` from `people.js`, and `gameFor`
from `games.js`, which is where the deployed bundle has them. Adjust if your exports differ.

## 3. Edits to existing files

**`src/maps.js`, `download()`**: add the log row to the existing batch:

```js
  if (request.method === "GET") {
    const day = (/* @__PURE__ */ new Date()).toISOString().slice(0, 10);
    ctx.waitUntil(env.DB.batch([
      env.DB.prepare("UPDATE game_maps SET downloads = downloads + 1 WHERE game = ? AND slug = ?").bind(game.key, slug),
      env.DB.prepare(
        "INSERT INTO game_downloads_daily (game, slug, day, count) VALUES (?, ?, ?, 1) ON CONFLICT (game, slug, day) DO UPDATE SET count = count + 1"
      ).bind(game.key, slug, day),
+     env.DB.prepare("INSERT INTO map_downloads (user_id, game, slug) VALUES (?, ?, ?)").bind(r.user.id, game.key, slug)
    ]));
  }
```

**`src/people.js`, `adminAreas()`**: add a tab after Messages:

```js
    ["messages", "/admin/messages", "Messages", r.admin],
+   ["downloads", "/admin/downloads", "Downloads", r.admin],
```

**`src/index.js`**: import the page and register the route in `GET_ROUTES`:

```js
+import { adminDownloadsPage } from "./admin_downloads.js";
 ...
   ["/admin/messages", adminMessagesPage],
+  ["/admin/downloads", adminDownloadsPage],
```

Then run `npx wrangler deploy`.

## Notes
- Fastdl transfers by game servers (`FASTDL_ROOT`) don't go through `download()`, so they aren't attributed
  to anyone. Only website downloads are logged, and those require a login.
- The table grows by one row per download. If it ever gets big, prune it with something like
  `DELETE FROM map_downloads WHERE created_at < strftime('%Y-%m-%dT%H:%M:%SZ','now','-180 days')`.
