ALTER TABLE `stats_contributions` MODIFY `amount` DECIMAL(9, 2);
ALTER TABLE `stats_contributions` MODIFY `suggested_amount` DECIMAL(9, 2);

ALTER TABLE `addons` MODIFY `total_contributions` DECIMAL(9, 2);
ALTER TABLE `addons` MODIFY `suggested_amount` DECIMAL(9, 2);
