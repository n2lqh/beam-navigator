-- A participant closes their session with notes shown at the next one (owner, 2026-10-30).
ALTER TABLE session ADD COLUMN closing_notes TEXT;
ALTER TABLE session ADD COLUMN closed_at TEXT;
