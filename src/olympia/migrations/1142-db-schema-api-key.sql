ALTER TABLE `api_key`
    MODIFY `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `type` int(10) unsigned NOT NULL,
    DROP FOREIGN KEY `api_key_user_id`,
    ADD CONSTRAINT `api_key_user_id_2b8305f7_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
