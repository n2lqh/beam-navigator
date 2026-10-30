-- QRZ lookups (requirements 4.9), kept apart from station records so a QRZ grid never
-- overwrites a roster or saved one. No credentials are ever stored here.
CREATE TABLE qrz_record (
  callsign TEXT PRIMARY KEY,
  name TEXT,
  grid TEXT,
  qth TEXT,
  lat REAL,
  lon REAL,
  geoloc TEXT,
  looked_up_at TEXT NOT NULL
);
