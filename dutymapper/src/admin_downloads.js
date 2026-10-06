import { esc, page, notFound, fmtNum, timeTag } from "./views.js";
import { USER_COLUMNS, adminNav, avatarHtml, nameHtml } from "./people.js";
import { gameFor } from "./games.js";

const PAGE_SIZE = 50;

// Who downloaded what: every logged-in map download, newest first. Filter by member and/or map.
export async function adminDownloadsPage(r) {
  if (!r.admin) return notFound(r);
  const { env, url } = r;
  const member = String(url.searchParams.get("member") || "").trim().replace(/^@/, "").slice(0, 40);
  const map = String(url.searchParams.get("map") || "").trim().slice(0, 80);
  const pageNo = Math.max(1, Number(url.searchParams.get("page")) || 1);
  const like = (s) => `%${s.replace(/[%_\\]/g, (c) => `\\${c}`)}%`;
  const where = [];
  const binds = [];
  if (member) {
    where.push("(u.profile_slug LIKE ? ESCAPE '\\' OR u.username LIKE ? ESCAPE '\\' OR u.display_name LIKE ? ESCAPE '\\' OR u.id = ?)");
    binds.push(like(member), like(member), like(member), member);
  }
  if (map) {
    where.push("(d.slug LIKE ? ESCAPE '\\' OR gm.name LIKE ? ESCAPE '\\')");
    binds.push(like(map), like(map));
  }
  const filter = where.length ? `WHERE ${where.join(" AND ")}` : "";
  const from = `FROM map_downloads d JOIN users u ON u.id = d.user_id
                LEFT JOIN game_maps gm ON gm.game = d.game AND gm.slug = d.slug ${filter}`;
  const [count, list] = await env.DB.batch([
    env.DB.prepare(`SELECT COUNT(*) AS n, COUNT(DISTINCT d.user_id) AS people, COUNT(DISTINCT d.game || '/' || d.slug) AS maps ${from}`).bind(...binds),
    env.DB.prepare(
      `SELECT d.id AS download_id, d.game, d.slug, d.created_at AS downloaded_at, gm.name AS map_name, ${USER_COLUMNS}
       ${from} ORDER BY d.id DESC LIMIT ? OFFSET ?`
    ).bind(...binds, PAGE_SIZE, (pageNo - 1) * PAGE_SIZE)
  ]);
  const { n: total, people, maps } = count.results[0];
  const rows = list.results.map((d) => {
    const game = gameFor(d.game);
    return `
      <tr>
        <td><span class="member-row">${avatarHtml(env, d, 32)}<span>${nameHtml(d)}<br><a class="dim" href="/admin/downloads?member=${encodeURIComponent(d.profile_slug || d.id)}">all their downloads</a></span></span></td>
        <td><a class="link" href="/${esc(d.game)}/maps/${esc(d.slug)}"><strong>${esc(d.map_name || d.slug)}</strong></a> <span class="dim">${esc(game?.short || d.game)}</span><br><a class="dim" href="/admin/downloads?map=${encodeURIComponent(d.slug)}">everyone who got it</a></td>
        <td>${timeTag(d.downloaded_at)}</td>
      </tr>`;
  }).join("");
  const params = (p) => {
    const s = new URLSearchParams();
    if (member) s.set("member", member);
    if (map) s.set("map", map);
    if (p > 1) s.set("page", String(p));
    const q = s.toString();
    return `/admin/downloads${q ? `?${q}` : ""}`;
  };
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  return page(r, "Downloads", `
    <main class="wrap admin">
      <span class="label">Admin</span>
      <h1 class="page-title">Downloads</h1>
      ${adminNav(r, "downloads")}
      <form class="admin-search" method="get" action="/admin/downloads">
        <label>Member <input name="member" value="${esc(member)}" placeholder="name or profile"></label>
        <label>Map <input name="map" value="${esc(map)}" placeholder="map name or slug"></label>
        <button class="btn small primary" type="submit">Search</button>
        ${member || map ? `<a class="btn small" href="/admin/downloads">Clear</a>` : ""}
      </form>
      <p class="note">${fmtNum(total)} download${total === 1 ? "" : "s"} of ${fmtNum(maps)} map${maps === 1 ? "" : "s"} by ${fmtNum(people)} member${people === 1 ? "" : "s"}${member || map ? " found" : ""}. Only website downloads by logged-in members are listed; fastdl transfers from game servers aren't.</p>
      ${rows ? `
      <div class="table-wrap">
        <table class="files uploads-table">
          <thead><tr><th>Member</th><th>Map</th><th>When</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      ${pages > 1 ? `
      <nav class="pager" aria-label="Pages">
        ${pageNo > 1 ? `<a class="btn" href="${params(pageNo - 1)}">← Newer</a>` : "<span></span>"}
        <span class="label">Page ${pageNo} of ${pages}</span>
        ${pageNo < pages ? `<a class="btn" href="${params(pageNo + 1)}">Older →</a>` : "<span></span>"}
      </nav>` : ""}` : `<p class="empty">No downloads${member || map ? " match that search" : " logged yet"}.</p>`}
    </main>`);
}
