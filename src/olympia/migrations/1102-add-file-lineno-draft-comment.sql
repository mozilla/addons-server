ALTER TABLE `log_activity_comment_draft`
  ADD COLUMN `filename` varchar(255) NULL,
  ADD COLUMN `lineno` integer UNSIGNED NULL,
  CHANGE `comments` `comment` longtext NOT NULL;
