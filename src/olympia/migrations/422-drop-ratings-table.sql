ALTER TABLE `ratings` DROP FOREIGN KEY `ratings_addon_id_fk`;
ALTER TABLE `ratings` DROP FOREIGN KEY `ratings_user_id_fk`;
ALTER TABLE `ratings` DROP FOREIGN KEY `ratings_body_fk`;
ALTER TABLE `ratings` DROP FOREIGN KEY `ratings_reply_to_fk3`;

ALTER TABLE `ratings_moderation_flags` DROP FOREIGN KEY `ratings_moderation_flags_rating_id_fk`;
ALTER TABLE `ratings_moderation_flags` DROP FOREIGN KEY `ratings_moderation_flags_user_id_fk`;

DROP INDEX `ratings_addon_id_idx` ON `ratings`;
DROP INDEX `ratings_user_id_idx` ON `ratings`;
DROP INDEX `ratings_moderation_flags_rating_id_idx` ON `ratings_moderation_flags`;
DROP INDEX `ratings_moderation_flags_user_id_idx` ON `ratings_moderation_flags`;

DROP TABLE `ratings`;

DROP TABLE `ratings_moderation_flags`;
