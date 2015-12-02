ALTER TABLE file_validation
    ADD COLUMN `signing_trivials` integer NOT NULL,
    ADD COLUMN `signing_lows` integer NOT NULL,
    ADD COLUMN `signing_mediums` integer NOT NULL,
    ADD COLUMN `signing_highs` integer NOT NULL,
    ADD COLUMN `passed_auto_validation` tinyint(1) NOT NULL;
