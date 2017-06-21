-- Drop old index first, if it exists.

-- Set the index_name or NULL if it doesn't exist
SET @KEY_ADDON_DATE_IDX := (
    SELECT INDEX_NAME FROM information_schema.STATISTICS WHERE
        TABLE_SCHEMA = (SELECT DATABASE()) AND
        TABLE_NAME = 'theme_user_counts' AND
        INDEX_NAME = 'addon_date_idx'
    LIMIT 1);

SET @QUERY_DROP_KEY_ADDON_DATE_IDX = IF(
    @KEY_ADDON_DATE_IDX IS NOT NULL,
    CONCAT('ALTER TABLE validation_job DROP KEY ', @KEY_ADDON_DATE_IDX, ';'),
    'SELECT 0;');

PREPARE stmt FROM @QUERY_DROP_KEY_ADDON_DATE_IDX;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Now create a proper
ALTER TABLE `theme_user_counts` ADD CONSTRAINT `theme_user_counts_date_cc9034dde90789f_uniq` UNIQUE (`date`, `addon_id`);
