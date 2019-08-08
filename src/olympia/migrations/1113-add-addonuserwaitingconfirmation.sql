CREATE TABLE `addons_users_pending_confirmation` (
    `id` integer UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `role` smallint NOT NULL,
    `listed` bool NOT NULL,
    `addon_id` integer UNSIGNED NOT NULL,
    `user_id` integer NOT NULL
);

ALTER TABLE `addons_users_pending_confirmation` ADD CONSTRAINT `addons_users_pending_confirmation_addon_id_9e12bbad_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
ALTER TABLE `addons_users_pending_confirmation` ADD CONSTRAINT `addons_users_pending_confirmation_user_id_3c4c2421_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
ALTER TABLE `addons_users_pending_confirmation` ADD CONSTRAINT `addons_users_pending_confirmation_addon_id_user_id_38e3bb32_uniq` UNIQUE (`addon_id`, `user_id`);
