ALTER TABLE `abuse_reports`
    ADD COLUMN `country_code` varchar(2),
    MODIFY `ip_address` varchar(255);
