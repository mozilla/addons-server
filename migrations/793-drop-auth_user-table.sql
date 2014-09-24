-- Those tables should now be pointing to the users table, not the auth_user table, since the switch to django1.6 and the custom user model.
ALTER TABLE `api_access` DROP FOREIGN KEY `user_id_api`;
ALTER TABLE `api_access` ADD CONSTRAINT `user_id_api` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `auth_message` DROP FOREIGN KEY `user_id_refs_id_650f49a6`;
ALTER TABLE `auth_message` ADD CONSTRAINT `user_id_refs_id_650f49a6` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `auth_user_groups` DROP FOREIGN KEY `user_id_refs_id_7ceef80f`;
ALTER TABLE `auth_user_groups` ADD CONSTRAINT `user_id_refs_id_7ceef80f` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `auth_user_user_permissions` DROP FOREIGN KEY `user_id_refs_id_dfbab7d`;
ALTER TABLE `auth_user_user_permissions` ADD CONSTRAINT `user_id_refs_id_dfbab7d` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `django_admin_log` DROP FOREIGN KEY `user_id_refs_id_c8665aa`;
ALTER TABLE `django_admin_log` ADD CONSTRAINT `user_id_refs_id_c8665aa` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `oauth_token` DROP FOREIGN KEY `user_id_refs_id_e213c7fc`;
ALTER TABLE `oauth_token` ADD CONSTRAINT `user_id_refs_id_e213c7fc` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `piston_consumer` DROP FOREIGN KEY `user_id_refs_id_aad30107`;
ALTER TABLE `piston_consumer` ADD CONSTRAINT `user_id_refs_id_aad30107` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `piston_token` DROP FOREIGN KEY `user_id_refs_id_efc02d17`;
ALTER TABLE `piston_token` ADD CONSTRAINT `user_id_refs_id_efc02d17` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

-- Now drop the auth_user table.
DROP TABLE `auth_user`;
