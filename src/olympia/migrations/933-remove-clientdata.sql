ALTER TABLE `reviews` DROP FOREIGN KEY `client_data_id_refs_id_c0e106c0`, DROP KEY `reviews_1446fb9b`, DROP COLUMN `client_data_id`;
ALTER TABLE `stats_contributions` DROP FOREIGN KEY `client_data_id_refs_id_d3f47e0e`, DROP KEY `stats_contributions_1446fb9b`, DROP COLUMN `client_data_id`;
DROP TABLE IF EXISTS `client_data`;
