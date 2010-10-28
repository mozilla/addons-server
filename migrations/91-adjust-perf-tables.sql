-- Just going to get rid of all the tables since they are empty and we're
-- changing the FKs and engines.
DROP TABLE IF EXISTS perf_results, perf_appversions, perf_osversions;

CREATE TABLE `perf_results` (
    `id` int(11) unsigned NOT NULL auto_increment,
    `addon_id` int(11) unsigned NOT NULL,
    `appversion_id` int(11) unsigned NOT NULL,
    `osversion_id` int(11) unsigned NOT NULL,
    `average` float NOT NULL default 0,
    `test` enum('tp', 'ts'),
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    PRIMARY KEY  (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE TABLE `perf_appversions` (
    `id` int(11) unsigned NOT NULL auto_increment,
    `app` enum('fx'),
    `version` varchar(255) NOT NULL default '',
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    PRIMARY KEY  (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE TABLE `perf_osversions` (
  `id` int(11) unsigned NOT NULL auto_increment,
  `os` varchar(255) NOT NULL default '',
  `version` varchar(255) NOT NULL default '',
  `created` datetime NOT NULL,
  `modified` datetime NOT NULL,
  PRIMARY KEY  (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

ALTER TABLE `perf_results` ADD CONSTRAINT `perf_results_addon_id_key` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);

ALTER TABLE `perf_results` ADD CONSTRAINT `perf_results_appversion_key` FOREIGN KEY (`appversion_id`) REFERENCES `perf_appversions` (`id`);

ALTER TABLE `perf_results` ADD CONSTRAINT `perf_results_osversion_key` FOREIGN KEY (`osversion_id`) REFERENCES `perf_osversions` (`id`);
