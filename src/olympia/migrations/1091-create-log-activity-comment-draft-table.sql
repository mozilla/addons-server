CREATE TABLE `log_activity_comment_draft` (
  `id` integer UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
  `created` datetime(6) NOT NULL,
  `modified` datetime(6) NOT NULL,
  `comments` longtext NOT NULL,
  `version_id` integer UNSIGNED NOT NULL,
  `user_id` integer NOT NULL
);

ALTER TABLE `log_activity_comment_draft`
  ADD CONSTRAINT `log_activity_comment_draft_version_id_b9633528_fk_versions_id`
  FOREIGN KEY (`version_id`)
  REFERENCES `versions` (`id`);

ALTER TABLE `log_activity_comment_draft`
  ADD CONSTRAINT `log_activity_comment_draft_user_id_52237469_fk_users_id`
  FOREIGN KEY (`user_id`)
  REFERENCES `users` (`id`);
