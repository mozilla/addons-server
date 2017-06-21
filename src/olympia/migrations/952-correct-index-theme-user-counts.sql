-- Drop old index first
DROP INDEX `addon_date_idx` ON `theme_user_counts`;

-- Now create a proper
ALTER TABLE `theme_user_counts` ADD CONSTRAINT `theme_user_counts_date_cc9034dde90789f_uniq` UNIQUE (`date`, `addon_id`);
