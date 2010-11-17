DROP TABLE IF EXISTS `submit_step`;
CREATE TABLE `submit_step` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `addon_id` int(11) UNSIGNED NOT NULL,
    `step` integer NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

ALTER TABLE `submit_step`
    ADD CONSTRAINT FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
