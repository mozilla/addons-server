ALTER TABLE `webapps_iarc_info` ADD UNIQUE (`addon_id`);
-- We can't do this yet b/c there are apps where this isn't true currently.
-- ALTER TABLE `webapps_iarc_info` ADD UNIQUE (`submission_id`);
ALTER TABLE `webapps_iarc_info` DROP KEY `addon_id_2`;
