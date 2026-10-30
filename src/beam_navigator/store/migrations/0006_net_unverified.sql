-- Example nets are labelled unverified until the operator checks them (spec 4.6).
ALTER TABLE net ADD COLUMN unverified INTEGER NOT NULL DEFAULT 0;
