ALTER TABLE `log_activity_comment_draft`
  ADD COLUMN `canned_response_id` integer UNSIGNED DEFAULT NULL;

ALTER TABLE `log_activity_comment_draft`
  ADD CONSTRAINT `log_activity_comment_canned_response_id_6a9271d5_fk_cannedres`
  FOREIGN KEY (`canned_response_id`)
  REFERENCES `cannedresponses` (`id`);
