 -- Make the old field nullable to prepare for its future removal.
ALTER TABLE `addons` MODIFY COLUMN `whiteboard` longtext NULL;

-- Note: if the migration fails for you locally, remove the 'UNSIGNED' next to addon_id below.
CREATE TABLE `review_whiteboard` (
    `created` datetime(6) NOT NULL,
    `modified` datetime(6) NOT NULL,
    `addon_id` integer UNSIGNED  NOT NULL PRIMARY KEY,
    `private` longtext NOT NULL,
    `public` longtext NOT NULL
);
ALTER TABLE `review_whiteboard` ADD CONSTRAINT `addon_id_refs_id_3aa22f51` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);

-- Move the whiteboard from the addons table to the new one
INSERT INTO `review_whiteboard` (`created`, `modified`, `addon_id`, `private`, `public`)
    SELECT `created`, `modified`, `id`, '', `whiteboard` FROM `addons` WHERE `whiteboard` != '';
