/* Follow-on from migration 938 -
Drop the (now obsolete) bio and old translations. */

/*  ** Note: FOREIGN KEY is prod's - you will need to change this for your
local DB ** */

/* Drop the constraint so we can clear the translations.*/
ALTER TABLE `users`
    DROP FOREIGN KEY `users_ibfk_1`;

/* Clear out the translations. */
DELETE FROM `translations` WHERE `id` in (SELECT `bio` FROM `users`);

/* Drop the old columns. */
ALTER TABLE `users`
    DROP COLUMN `bio`,
    DROP COLUMN lang,
    DROP COLUMN region;
