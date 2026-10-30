-- Beam Navigator schema v1 (requirements section 3). Rotator profiles and the
-- command log arrive in a later migration with Milestone 2.

CREATE TABLE operator_profile (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  callsign TEXT,
  home_grid TEXT NOT NULL,
  lat REAL,
  lon REAL,
  units TEXT NOT NULL CHECK (units IN ('km', 'mi')),
  timezone TEXT NOT NULL,
  home_region TEXT,
  is_active INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX one_active_profile ON operator_profile (is_active) WHERE is_active = 1;

CREATE TABLE alias (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL CHECK (kind IN ('grid', 'coords', 'station', 'heading')),
  value TEXT NOT NULL
);

CREATE TABLE station (
  id INTEGER PRIMARY KEY,
  callsign TEXT NOT NULL UNIQUE,
  name TEXT,
  grid TEXT,
  qth TEXT,
  lat REAL,
  lon REAL,
  source TEXT NOT NULL CHECK (source IN ('saved', 'roster')),
  notes TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);

CREATE TABLE net (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  weekday INTEGER CHECK (weekday BETWEEN 0 AND 6),
  start_time TEXT,
  timezone TEXT,
  frequency_mhz REAL,
  channel TEXT,
  mode TEXT,
  band TEXT,
  default_controller_call TEXT,
  default_controller_grid TEXT,
  archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE session (
  id INTEGER PRIMARY KEY,
  net_id INTEGER NOT NULL REFERENCES net (id) ON DELETE RESTRICT,
  date TEXT NOT NULL,
  controller_call TEXT,
  controller_grid TEXT,
  status TEXT NOT NULL CHECK (status IN ('active', 'closed', 'imported')),
  raw_text TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX session_net_date ON session (net_id, date);

CREATE TABLE checkin (
  id INTEGER PRIMARY KEY,
  session_id INTEGER NOT NULL REFERENCES session (id) ON DELETE RESTRICT,
  sequence INTEGER,
  logged_at TEXT,
  callsign TEXT NOT NULL,
  name TEXT,
  grid TEXT,
  qth TEXT,
  report TEXT,
  notes TEXT,
  published_bearing TEXT,
  heard_state TEXT CHECK (heard_state IN ('heard', 'weak', 'not_heard', 'relay')),
  relay_call TEXT
);

CREATE INDEX checkin_session ON checkin (session_id);
CREATE INDEX checkin_callsign ON checkin (callsign);
