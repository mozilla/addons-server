ALTER TABLE `groups`
    MODIFY `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
    MODIFY `name` varchar(255) NOT NULL,
    MODIFY `rules` longtext NOT NULL,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL;
