/* Add the new columns and drop the constraints so we can clear the translations.*/
ALTER TABLE `cannedresponses`
    ADD COLUMN `_name` varchar(255) NOT NULL default '',
    ADD COLUMN `_response` varchar(1024) NOT NULL default '',
    DROP FOREIGN KEY `name_refs_id_8865ac11`,
    DROP FOREIGN KEY `response_refs_id_8865ac11`;

/* Copy across the translated values.  Everything is in en-us in this table so
   don't need to worry about multiple translations per record. */
UPDATE `cannedresponses`
    SET `_name` = (SELECT `localized_string` FROM `translations` WHERE `id`=`name`),
        `_response` = (SELECT `localized_string` FROM `translations` WHERE `id`=`response`);

/* Clear out the now obsolete translations. */
DELETE FROM `translations` WHERE `id` in (SELECT `name` FROM `cannedresponses`);
DELETE FROM `translations` WHERE `id` in (SELECT `response` FROM `cannedresponses`);

/* Drop the old columns and rename the new ones to take their places. */
ALTER TABLE `cannedresponses`
    DROP COLUMN `name`,
    DROP COLUMN `response`,
    CHANGE COLUMN `_name` `name` varchar(255) NOT NULL default '',
    CHANGE COLUMN `_response` `response` varchar(1024) NOT NULL default '';
