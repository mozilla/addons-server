ALTER TABLE `file_validation`
    DROP COLUMN `signing_trivials`,
    DROP COLUMN `signing_lows`, 
    DROP COLUMN `signing_mediums`,
    DROP COLUMN `signing_highs`,
    DROP COLUMN `passed_auto_validation`;
DROP TABLE `validation_annotations`;
