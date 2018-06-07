/* Add the new column.*/
ALTER TABLE `reviews`
    ADD COLUMN `text_body` longtext NULL;

/* Copy across the translated values.  There are some ratings that have multiple
localizations so we're going to use latest (most recent) localization. */
UPDATE `reviews`
    SET `text_body` = (
        SELECT `localized_string` FROM `translations`
        WHERE `translations`.`id` = `reviews`.`body`
        ORDER BY `translations`.`modified` DESC
        LIMIT 1);

/* Clean-up where old column is dropped, etc, in a subsequent migration. */
