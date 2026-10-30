-- The band table (requirements 4.1, 4.7, 4.8: data, not code) and small app settings.
-- mhz is the band's nominal frequency; it drives the coarse-location note.

CREATE TABLE band (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  mhz REAL NOT NULL CHECK (mhz > 0),
  long_path INTEGER NOT NULL DEFAULT 0
);

INSERT INTO band (name, mhz, long_path) VALUES
  ('10 m', 28, 1),
  ('6 m', 50, 1),
  ('2 m', 144, 0),
  ('1.25 m', 222, 0),
  ('70 cm', 432, 0),
  ('33 cm', 902, 0),
  ('23 cm', 1296, 0);

CREATE TABLE setting (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
