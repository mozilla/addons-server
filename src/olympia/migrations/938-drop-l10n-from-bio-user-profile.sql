/* FOREIGN KEY is prod's - you will need to change this for your local DB */

/* Add the new column and drop the constraint so we can clear the translations.*/
ALTER TABLE `users`
    ADD COLUMN `_bio` longtext NULL,
    DROP FOREIGN KEY `users_ibfk_1`;

/* Copy across the translated values.  There are some users that have multiple
localizations so we're going to use the default locale (lang) localization. */
UPDATE `users`
    SET `_bio` = (
        SELECT `localized_string` FROM `translations`
        WHERE `id`=`bio` AND `locale`=`lang`);

/* Clear out the now obsolete translations. */
DELETE FROM `translations` WHERE `id` in (SELECT `bio` FROM `users`);

/* Drop the old columns and rename bio_ to take the place of bio. */
ALTER TABLE `users`
    DROP COLUMN `bio`,
    DROP COLUMN lang,
    DROP COLUMN region,
    CHANGE COLUMN `_bio` `bio` longtext NULL;
