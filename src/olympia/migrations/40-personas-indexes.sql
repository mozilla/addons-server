-- Make personas queries faster
CREATE INDEX `personas_movers_idx` ON personas (movers);
CREATE INDEX `personas_popularity_idx` ON personas (popularity);
