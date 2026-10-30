-- A net's preferred rotator (spec 3). Deleting the rotator clears the preference.
ALTER TABLE net ADD COLUMN rotator_id INTEGER REFERENCES rotator_profile (id) ON DELETE SET NULL;
