CREATE TABLE `theme_user_counts` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `addon_id` integer UNSIGNED NOT NULL,
    `count` integer UNSIGNED NOT NULL,
    `date` date NOT NULL
);

ALTER TABLE `theme_user_counts` ADD CONSTRAINT `addon_id_refs_id_ac19f783` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
CREATE INDEX addon_date_idx ON theme_user_counts (addon_id, date);

INSERT INTO waffle_switch_amo (name, active, created, modified, note) VALUES ('theme-stats', 0, NOW(), NOW(), 'Allow access to theme stat pages');
