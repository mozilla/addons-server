ALTER TABLE `categories`
    MODIFY `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
    MODIFY `addontype_id` int(10) unsigned NOT NULL,
    MODIFY `application_id` int(10) unsigned DEFAULT NULL,
    MODIFY `weight` int(11) NOT NULL,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `count` int(11) NOT NULL,
    MODIFY `slug` varchar(50) NOT NULL,
    MODIFY `misc` tinyint(1) NOT NULL;
