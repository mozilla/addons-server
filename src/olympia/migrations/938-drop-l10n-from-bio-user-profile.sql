/* Add the new column.*/
ALTER TABLE `users`
    ADD COLUMN `biography` longtext NULL;

/* Copy across the translated values.  There are some users that have multiple
localizations so we're going to use the default locale (lang) localization. */
UPDATE `users`
    SET `biography` = (
        SELECT `localized_string` FROM `translations`
        WHERE `translations`.`id` = `users`.`bio` AND
              `translations`.`locale` = `users`.`lang`);

/* Cover the edge case where the profile has an en-US localization but not in
their locale. */
UPDATE `users`
    SET `biography` = (
        SELECT `localized_string` FROM `translations`
        WHERE `translations`.`id` = `users`.`bio` AND
              `translations`.`locale` = 'en-US')
    WHERE `biography` IS NULL;

/* Clean-up where old columns are dropped, etc, in a subsequent migration. */
