CREATE TABLE `reviewer_scores` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `user_id` int(11) unsigned NOT NULL,
    `score` smallint NOT NULL,
    `note` varchar(255) NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `reviewer_scores`
    ADD CONSTRAINT `reviewer_scores_user_id_fk`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

CREATE INDEX `reviewer_scores_created_idx` ON `reviewer_scores` (`created`);
CREATE INDEX `reviewer_scores_user_id_idx` ON `reviewer_scores` (`user_id`);
