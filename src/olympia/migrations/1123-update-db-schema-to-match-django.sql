ALTER TABLE `abuse_reports`
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `guid` varchar(255),
    MODIFY `state` smallint(5) unsigned NOT NULL;

ALTER TABLE `addons`
    MODIFY `addontype_id` int(10) unsigned NOT NULL,
    MODIFY `average_daily_users` int(10) unsigned NOT NULL,
    MODIFY `averagerating` double,
    MODIFY `bayesianrating` double NOT NULL,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `current_version` int(10) unsigned,
    MODIFY `description` int(10) unsigned,
    MODIFY `developercomments` int(10) unsigned,
    MODIFY `eula` int(10) unsigned,
    MODIFY `homepage` int(10) unsigned,
    MODIFY `icon_hash` varchar(8),
    MODIFY `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
    MODIFY `inactive` tinyint(1) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `name` int(10) unsigned,
    MODIFY `last_updated` datetime(6),
    MODIFY `privacypolicy` int(10) unsigned,
    MODIFY `publicstats` tinyint(1) NOT NULL,
    MODIFY `requires_payment` tinyint(1) NOT NULL,
    MODIFY `status` int(10) unsigned NOT NULL,
    MODIFY `summary` int(10) unsigned,
    MODIFY `supportemail` int(10) unsigned,
    MODIFY `supporturl` int(10) unsigned,
    MODIFY `textreviewscount` int(10) unsigned NOT NULL,
    MODIFY `totaldownloads` int(10) unsigned NOT NULL,
    MODIFY `totalreviews` int(10) unsigned NOT NULL,
    MODIFY `viewsource` tinyint(1) NOT NULL,
    MODIFY `weeklydownloads` int(10) unsigned
    , DROP `whiteboard`  /* Comment out this line if this fails locally */
;
