ALTER TABLE `log_activity_comment_draft`
  ADD COLUMN `filename` varchar(255) NOT NULL,
  ADD COLUMN `lineno` integer UNSIGNED NOT NULL,
  CHANGE `comments` `comment` longtext NOT NULL;
