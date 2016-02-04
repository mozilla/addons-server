INSERT INTO download_sources (name, type) VALUES
    ('mkt-home', 'full'),
    ('mkt-featured', 'full'),
    ('mkt-category', 'full'),
    ('mkt-detail', 'full'),
    ('mkt-detail-upsell', 'full'),
    ('mkt-search', 'full'),
    ('mkt-ss', 'full'),
    ('mkt-user-profile', 'full');


CREATE TABLE `client_data` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `download_source_id` int(11) unsigned NULL,
    `device_type` varchar(255) NOT NULL,
    `user_agent` varchar(255) NOT NULL,
    `is_chromeless` bool,
    `language` varchar(7) NOT NULL,
    `region` int(11) unsigned NULL,
    UNIQUE (`download_source_id`, `device_type`, `user_agent`, `is_chromeless`, `language`, `region`)
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `client_data` ADD CONSTRAINT `download_source_id_refs_id_b71b78fb` FOREIGN KEY (`download_source_id`) REFERENCES `download_sources` (`id`);

ALTER TABLE users_install ADD COLUMN client_data_id int(11) unsigned;
ALTER TABLE `users_install` ADD CONSTRAINT `client_data_id_refs_id_15062d7f` FOREIGN KEY (`client_data_id`) REFERENCES `client_data` (`id`);
ALTER TABLE stats_contributions ADD COLUMN client_data_id int(11) unsigned;
ALTER TABLE `stats_contributions` ADD CONSTRAINT `client_data_id_refs_id_c8ef1728` FOREIGN KEY (`client_data_id`) REFERENCES `client_data` (`id`);
ALTER TABLE reviews ADD COLUMN client_data_id int(11) unsigned;
ALTER TABLE `reviews` ADD CONSTRAINT `client_data_id_refs_id_d160c5ba` FOREIGN KEY (`client_data_id`) REFERENCES `client_data` (`id`);

ALTER TABLE `users_install` ADD CONSTRAINT UNIQUE (`addon_id`, `user_id`, `client_data_id`);
