CREATE TABLE `perf_results` (
    `id` int(11) unsigned NOT NULL auto_increment,
    `addon_id` int(11) unsigned NOT NULL,
    `appversion_id` int(11) unsigned NOT NULL,
    `average` float NOT NULL default 0,
    `os` varchar(255) NOT NULL default '',
    `test` enum('ts'),
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    PRIMARY KEY  (`id`)
) DEFAULT CHARSET=utf8;

CREATE TABLE `perf_appversions` (
    `id` int(11) unsigned NOT NULL auto_increment,
    `app` enum('fx'),
    `version` varchar(255) NOT NULL default '',
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    PRIMARY KEY  (`id`)
) DEFAULT CHARSET=utf8;

ALTER TABLE `perf_results` ADD CONSTRAINT `perf_results_addon_id_key` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);

ALTER TABLE `perf_results` ADD CONSTRAINT `perf_results_appversion_key` FOREIGN KEY (`appversion_id`) REFERENCES `perf_appversions` (`id`);
