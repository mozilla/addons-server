-- Drop old index first, if it exists.

-- Set to index_name (addon_date_idx) or NULL if it doesn't exist
SET @KEY_ADDON_DATE_IDX := (
    SELECT INDEX_NAME FROM information_schema.STATISTICS WHERE
        TABLE_SCHEMA = (SELECT DATABASE()) AND
        TABLE_NAME = 'theme_user_counts' AND
        INDEX_NAME = 'addon_date_idx'
    -- Need the limit 1 here because the query will match two columns
    -- because the index is a composite index on (addon_id, date)
    -- and since we re-use it below in the prepared-statement we want
    -- only the name.
    LIMIT 1);

SET @QUERY_DROP_KEY_ADDON_DATE_IDX = IF(
    @KEY_ADDON_DATE_IDX IS NOT NULL,
    CONCAT('ALTER TABLE theme_user_counts DROP KEY ', @KEY_ADDON_DATE_IDX, ';'),
    'SELECT 0;');

PREPARE stmt FROM @QUERY_DROP_KEY_ADDON_DATE_IDX;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Now create our new, proper index.
ALTER TABLE `theme_user_counts` ADD CONSTRAINT `theme_user_counts_date_cc9034dde90789f_uniq` UNIQUE (`date`, `addon_id`);
