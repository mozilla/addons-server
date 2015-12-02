INSERT IGNORE INTO `waffle_flag`
    (name, everyone, percent, superusers, staff, authenticated, rollout, note) VALUES
    ('allow-pre-auth',0,NULL,0,0,0,0, 'Allow pre-auth of paypal payments');

CREATE TABLE `users_preapproval` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `user_id` int(11) unsigned NOT NULL UNIQUE,
    `paypal_key` varchar(255),
    `paypal_expiry` date
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `users_preapproval` ADD CONSTRAINT `user_id_refs_id_idx` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
CREATE INDEX `users_preapproval_idx` ON `users_preapproval` (`user_id`);
