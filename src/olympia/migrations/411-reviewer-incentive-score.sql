DROP TABLE IF EXISTS `reviewer_scores`;

CREATE TABLE `reviewer_scores` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `user_id` int(11) unsigned NOT NULL,
    `addon_id` int(11) unsigned,
    `score` smallint NOT NULL,
    `note_key` smallint NOT NULL DEFAULT 0,
    `note` varchar(255) NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `reviewer_scores`
    ADD CONSTRAINT `reviewer_scores_user_id_fk`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
    ON DELETE CASCADE;
ALTER TABLE `reviewer_scores`
    ADD CONSTRAINT `reviewer_scores_addon_id_fk`
    FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`)
    ON DELETE SET NULL;

CREATE INDEX `reviewer_scores_created_idx` ON `reviewer_scores` (`created`);
CREATE INDEX `reviewer_scores_user_id_idx` ON `reviewer_scores` (`user_id`);


INSERT INTO waffle_switch_amo (name, active, note)
    VALUES ('reviewer-incentive-points', 0, 'This enables awarding of points to reviewers.');
INSERT INTO waffle_switch_mkt (name, active, note)
    VALUES ('reviewer-incentive-points', 0, 'This enables awarding of points to reviewers.');
