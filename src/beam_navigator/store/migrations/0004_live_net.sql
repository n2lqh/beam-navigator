-- Tonight's substitute controller may be known only by a measured bearing (spec 4.4).
ALTER TABLE session ADD COLUMN controller_bearing REAL
  CHECK (controller_bearing >= 0 AND controller_bearing < 360);
