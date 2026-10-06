-- One row per map download by a logged-in member, so admins can see who downloaded what.
-- (game_maps.downloads and game_downloads_daily only ever stored counts.)
CREATE TABLE IF NOT EXISTS map_downloads (
  id INTEGER PRIMARY KEY,
  user_id TEXT NOT NULL,
  game TEXT NOT NULL,
  slug TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS map_downloads_user ON map_downloads (user_id, id);
CREATE INDEX IF NOT EXISTS map_downloads_map ON map_downloads (game, slug, id);
