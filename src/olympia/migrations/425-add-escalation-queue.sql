CREATE TABLE `escalation_queue` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` int(11) unsigned NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `escalation_queue` ADD CONSTRAINT `escalation_queue_addon_id_fk` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);

CREATE INDEX `escalation_queue_addon_id_idx` ON `escalation_queue` (`addon_id`);
CREATE INDEX `escalation_queue_created_idx` ON `escalation_queue` (`created`);
