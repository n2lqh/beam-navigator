-- Rotator profiles and the command log (requirements 3, 4.7). A new profile is
-- always simulated; live needs a passed connection test (invariant 8).

CREATE TABLE rotator_profile (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  adapter TEXT NOT NULL CHECK (adapter IN ('simulation', 'pstrotator', 'hamlib')),
  host TEXT,
  port INTEGER,
  az_min REAL NOT NULL,
  az_max REAL NOT NULL,
  offset REAL NOT NULL DEFAULT 0,
  speed_deg_per_s REAL,
  bands TEXT NOT NULL DEFAULT '',
  live INTEGER NOT NULL DEFAULT 0,
  connection_tested INTEGER NOT NULL DEFAULT 0,
  CHECK (az_max > az_min)
);

CREATE TABLE rotator_command (
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  rotator_id INTEGER NOT NULL REFERENCES rotator_profile (id) ON DELETE RESTRICT,
  target_label TEXT,
  requested_true REAL,
  sent TEXT,
  ok INTEGER NOT NULL,
  message TEXT NOT NULL,
  measured REAL
);

CREATE INDEX rotator_command_recent ON rotator_command (rotator_id, id);
