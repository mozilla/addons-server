-- Django's way of creating primary keys doesn't use UNSIGNED columns. So if we
-- want Django created tables (like auth_messages, or django_admin_log) to be
-- able to FK to the users table, we need users.id to NOT be UNSIGNED.

-- Increase the interactive timeout, or the schematic utility might be cut before the end.
SET interactive_timeout=1800;

-- Remove the constraints for the current tables pointing to the users table.
ALTER TABLE `abuse_reports` DROP FOREIGN KEY `reporter_id_refs_id_12d88e23`;
ALTER TABLE `abuse_reports` DROP FOREIGN KEY `user_id_refs_id_12d88e23`;
ALTER TABLE `addons_collections` DROP FOREIGN KEY `addons_collections_ibfk_3`;
ALTER TABLE `addons_users` DROP FOREIGN KEY `addons_users_ibfk_2`;
ALTER TABLE `app_collections_curators` DROP FOREIGN KEY `app_collections_curators_userprofile_id`;
ALTER TABLE `approvals` DROP FOREIGN KEY `approvals_ibfk_1`;
ALTER TABLE `collection_subscriptions` DROP FOREIGN KEY `collections_subscriptions_ibfk_2`;
ALTER TABLE `collections` DROP FOREIGN KEY `collections_ibfk_7`;
ALTER TABLE `collections_users` DROP FOREIGN KEY `collections_users_ibfk_2`;
ALTER TABLE `collections_votes` DROP FOREIGN KEY `collections_votes_ibfk_2`;
ALTER TABLE `comm_notes_read` DROP FOREIGN KEY `userprofile_id_refs_id_4586e76`;
ALTER TABLE `comm_thread_cc` DROP FOREIGN KEY `thread_cc_user_id_key`;
ALTER TABLE `comm_thread_notes` DROP FOREIGN KEY `thread_notes_author_id_key`;
ALTER TABLE `comm_thread_tokens` DROP FOREIGN KEY `thread_tokens_user_id_key`;
ALTER TABLE `editor_subscriptions` DROP FOREIGN KEY `editor_subscriptions_ibfk_1`;
ALTER TABLE `file_uploads` DROP FOREIGN KEY `file_uploads_ibfk_1`;
ALTER TABLE `groups_users` DROP FOREIGN KEY `groups_users_ibfk_4`;
ALTER TABLE `hubrsskeys` DROP FOREIGN KEY `hubrsskeys_ibfk_1`;
ALTER TABLE `log_activity` DROP FOREIGN KEY `user_id_refs_id_3fa7a30a`;
ALTER TABLE `log_activity_mkt` DROP FOREIGN KEY `user_id_refs_user_id_ee305b55`;
ALTER TABLE `log_activity_user` DROP FOREIGN KEY `user_id_refs_id_e987c199`;
ALTER TABLE `log_activity_user_mkt` DROP FOREIGN KEY `user_id_refs_id_2eb55c34`;
ALTER TABLE `payment_accounts` DROP FOREIGN KEY `user_id_refs_id_4f9c3df5`;
ALTER TABLE `payments_seller` DROP FOREIGN KEY `user_id_refs_id_29692a2a`;
ALTER TABLE `reviewer_scores` DROP FOREIGN KEY `reviewer_scores_user_id_fk`;
ALTER TABLE `reviews` DROP FOREIGN KEY `reviews_ibfk_2`;
ALTER TABLE `reviews_moderation_flags` DROP FOREIGN KEY `reviews_moderation_flags_ibfk_2`;
ALTER TABLE `theme_locks` DROP FOREIGN KEY `reviewer_id_refs_id_fk`;
ALTER TABLE `users_install` DROP FOREIGN KEY `user_id_refs_id`;
ALTER TABLE `users_notifications` DROP FOREIGN KEY `users_notifications_ibfk_1`;
ALTER TABLE `users_versioncomments` DROP FOREIGN KEY `users_versioncomments_ibfk_1`;
ALTER TABLE `versioncomments` DROP FOREIGN KEY `versioncomments_ibfk_2`;
ALTER TABLE `waffle_flag_users` DROP FOREIGN KEY `flag_userprofile_id`;


-- Now change the users.id column to NOT be UNSIGNED.
LOCK TABLES `users` WRITE;
ALTER TABLE `users` MODIFY COLUMN `id` int(11) NOT NULL AUTO_INCREMENT;
UNLOCK TABLES;


-- And change the table columns that are currently pointing to the users table, to NOT be UNSIGNED, then recreate the constraints.
ALTER TABLE `abuse_reports` MODIFY COLUMN `reporter_id` int(11) DEFAULT NULL;
ALTER TABLE `abuse_reports` ADD CONSTRAINT `reporter_id_refs_id_12d88e23` FOREIGN KEY (`reporter_id`) REFERENCES `users` (`id`);

ALTER TABLE `abuse_reports` MODIFY COLUMN `user_id` int(11) DEFAULT NULL;
ALTER TABLE `abuse_reports` ADD CONSTRAINT `user_id_refs_id_12d88e23` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `addons_collections` MODIFY COLUMN `user_id` int(11) DEFAULT NULL;
ALTER TABLE `addons_collections` ADD CONSTRAINT `addons_collections_ibfk_3` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `addons_users` MODIFY COLUMN `user_id` int(11) NOT NULL DEFAULT '0';
ALTER TABLE `addons_users` ADD CONSTRAINT `addons_users_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `app_collections_curators` MODIFY COLUMN `userprofile_id` int(11) NOT NULL;
ALTER TABLE `app_collections_curators` ADD CONSTRAINT `app_collections_curators_userprofile_id` FOREIGN KEY (`userprofile_id`) REFERENCES `users` (`id`);

ALTER TABLE `approvals` MODIFY COLUMN `user_id` int(11) NOT NULL DEFAULT '0';
ALTER TABLE `approvals` ADD CONSTRAINT `approvals_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `collection_subscriptions` MODIFY COLUMN `user_id` int(11) NOT NULL;
ALTER TABLE `collection_subscriptions` ADD CONSTRAINT `collections_subscriptions_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `collections` MODIFY COLUMN `author_id` int(11) DEFAULT NULL;
ALTER TABLE `collections` ADD CONSTRAINT `collections_ibfk_7` FOREIGN KEY (`author_id`) REFERENCES `users` (`id`);

ALTER TABLE `collections_users` MODIFY COLUMN `user_id` int(11) NOT NULL DEFAULT '0';
ALTER TABLE `collections_users` ADD CONSTRAINT `collections_users_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `collections_votes` MODIFY COLUMN `user_id` int(11) NOT NULL DEFAULT '0';
ALTER TABLE `collections_votes` ADD CONSTRAINT `collections_votes_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `comm_notes_read` MODIFY COLUMN `user_id` int(11) NOT NULL;
ALTER TABLE `comm_notes_read` ADD CONSTRAINT `userprofile_id_refs_id_4586e76` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `comm_thread_cc` MODIFY COLUMN `user_id` int(11) NOT NULL;
ALTER TABLE `comm_thread_cc` ADD CONSTRAINT `thread_cc_user_id_key` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `comm_thread_notes` MODIFY COLUMN `author_id` int(11) NOT NULL;
ALTER TABLE `comm_thread_notes` ADD CONSTRAINT `thread_notes_author_id_key` FOREIGN KEY (`author_id`) REFERENCES `users` (`id`);

ALTER TABLE `comm_thread_tokens` MODIFY COLUMN `user_id` int(11) NOT NULL;
ALTER TABLE `comm_thread_tokens` ADD CONSTRAINT `thread_tokens_user_id_key` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `editor_subscriptions` MODIFY COLUMN `user_id` int(11) NOT NULL;
ALTER TABLE `editor_subscriptions` ADD CONSTRAINT `editor_subscriptions_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `file_uploads` MODIFY COLUMN `user_id` int(11) DEFAULT NULL;
ALTER TABLE `file_uploads` ADD CONSTRAINT `file_uploads_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `groups_users` MODIFY COLUMN `user_id` int(11) NOT NULL DEFAULT '0';
ALTER TABLE `groups_users` ADD CONSTRAINT `groups_users_ibfk_4` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `hubrsskeys` MODIFY COLUMN `user_id` int(11) DEFAULT NULL;
ALTER TABLE `hubrsskeys` ADD CONSTRAINT `hubrsskeys_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `log_activity` MODIFY COLUMN `user_id` int(11) DEFAULT NULL;
ALTER TABLE `log_activity` ADD CONSTRAINT `user_id_refs_id_3fa7a30a` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `log_activity_mkt` MODIFY COLUMN `user_id` int(11) DEFAULT NULL;
ALTER TABLE `log_activity_mkt` ADD CONSTRAINT `user_id_refs_user_id_ee305b55` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `log_activity_user` MODIFY COLUMN `user_id` int(11) NOT NULL;
ALTER TABLE `log_activity_user` ADD CONSTRAINT `user_id_refs_id_e987c199` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `log_activity_user_mkt` MODIFY COLUMN `user_id` int(11) NOT NULL;
ALTER TABLE `log_activity_user_mkt` ADD CONSTRAINT `user_id_refs_id_2eb55c34` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `payment_accounts` MODIFY COLUMN `user_id` int(11) NOT NULL;
ALTER TABLE `payment_accounts` ADD CONSTRAINT `user_id_refs_id_4f9c3df5` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `payments_seller` MODIFY COLUMN `user_id` int(11) NOT NULL;
ALTER TABLE `payments_seller` ADD CONSTRAINT `user_id_refs_id_29692a2a` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `reviewer_scores` MODIFY COLUMN `user_id` int(11) NOT NULL;
ALTER TABLE `reviewer_scores` ADD CONSTRAINT `reviewer_scores_user_id_fk` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `reviews` MODIFY COLUMN `user_id` int(11) NOT NULL DEFAULT '0';
ALTER TABLE `reviews` ADD CONSTRAINT `reviews_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `reviews_moderation_flags` MODIFY COLUMN `user_id` int(11) DEFAULT NULL;
ALTER TABLE `reviews_moderation_flags` ADD CONSTRAINT `reviews_moderation_flags_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `theme_locks` MODIFY COLUMN `reviewer_id` int(11) NOT NULL;
ALTER TABLE `theme_locks` ADD CONSTRAINT `reviewer_id_refs_id_fk` FOREIGN KEY (`reviewer_id`) REFERENCES `users` (`id`);

ALTER TABLE `users_install` MODIFY COLUMN `user_id` int(11) NOT NULL;
ALTER TABLE `users_install` ADD CONSTRAINT `user_id_refs_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `users_notifications` MODIFY COLUMN `user_id` int(11) NOT NULL;
ALTER TABLE `users_notifications` ADD CONSTRAINT `users_notifications_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `users_versioncomments` MODIFY COLUMN `user_id` int(11) NOT NULL;
ALTER TABLE `users_versioncomments` ADD CONSTRAINT `users_versioncomments_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `versioncomments` MODIFY COLUMN `user_id` int(11) NOT NULL DEFAULT '0';
ALTER TABLE `versioncomments` ADD CONSTRAINT `versioncomments_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `waffle_flag_users` MODIFY COLUMN `userprofile_id` int(11) NOT NULL;
ALTER TABLE `waffle_flag_users` ADD CONSTRAINT `flag_userprofile_id` FOREIGN KEY (`userprofile_id`) REFERENCES `users` (`id`);
