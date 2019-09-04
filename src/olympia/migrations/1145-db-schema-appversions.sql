ALTER TABLE `appversions`
    MODIFY `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
    MODIFY `application_id` int(10) unsigned NOT NULL,
    MODIFY `version` varchar(255) NOT NULL,
    MODIFY `version_int` bigint(20) NOT NULL,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL;
