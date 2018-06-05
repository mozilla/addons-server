-- Note: if the migration fails for you locally, remove the 'UNSIGNED' next to version_id below.
ALTER TABLE `reviewer_scores`
	ADD COLUMN `version_id` INTEGER UNSIGNED REFERENCES `versions` (`id`);
CREATE INDEX `reviewer_scores_version_id`
	ON `reviewer_scores` (`version_id`);
