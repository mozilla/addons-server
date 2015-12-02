ALTER TABLE `tags` ADD COLUMN `num_addons` int(50) NOT NULL DEFAULT 0;
UPDATE `tags`, `tag_stat` SET `tags`.`num_addons`=`tag_stat`.`num_addons` WHERE `tags`.`id` = `tag_stat`.`tag_id`;
DROP INDEX blacklisted_idx ON tags;
CREATE INDEX tag_blacklisted_num_addons_idx ON tags (blacklisted, num_addons);
