-- Find all addon name translations with an empty string, and update them to
-- have "Untitled" instead. The subselect to find the translations is wrapped
-- in a SELECT ... FROM because you can't directly UPDATE a table with a
-- subquery on the same table.
UPDATE `translations` SET `localized_string` = 'Untitled'
WHERE `id` IN (SELECT `id` FROM (
    SELECT `addons`.`name` AS `id` FROM `addons`
    INNER JOIN `translations` ON `addons`.`name` = `translations`.`id`
    WHERE `translations`.`localized_string` = '') AS dummy)
AND locale = 'en-US';

