DROP TABLE IF EXISTS `users_notifications`;
CREATE TABLE `users_notifications` (
      `id` int(11) unsigned NOT NULL AUTO_INCREMENT,
      `user_id` int(11) NOT NULL,
      `notification_id` int(11) NOT NULL,
      `created` datetime DEFAULT NULL,
      `modified` datetime DEFAULT NULL,
      `enabled` tinyint(1) DEFAULT NULL,
      PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

ALTER TABLE `users_notifications`
    ADD CONSTRAINT FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
