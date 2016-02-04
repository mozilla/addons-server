ALTER TABLE users_install DROP INDEX `addon_id`;
ALTER TABLE users_install DROP INDEX `addon_id_2`;
ALTER TABLE users_install ADD UNIQUE `addon_id`
        (`addon_id`,`user_id`, `client_data_id`, `install_type`);
