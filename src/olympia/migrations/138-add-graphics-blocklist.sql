--
-- Bug 628793: Graphics driver blocklist XML
--

DROP TABLE IF EXISTS `blgfxdrivers`;
CREATE TABLE `blgfxdrivers` (
  `id` int(11) unsigned NOT NULL auto_increment,
  `guid` varchar(255) default NULL,
  `os` varchar(255) default NULL,
  `vendor` varchar(255) default NULL,
  `devices` varchar(255) default NULL,
  `feature` varchar(255) default NULL,
  `feature_status` varchar(255) default NULL,
  `driver_version` varchar(255) default NULL,
  `driver_version_comparator` varchar(255) default NULL,
  `created` datetime NOT NULL default '0000-00-00 00:00:00',
  `modified` datetime NOT NULL default '0000-00-00 00:00:00',
  PRIMARY KEY  (`id`),
  KEY `guid` (`guid`(128))
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8;

-- Some data to test if you want (not something to put in production)
-- INSERT INTO `blgfxdrivers` VALUES
--    (9, '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}', 'WINNT 6.1', '0xabcd', '0x2783 0x1234 0x2782', 'DIRECT2D', 'BLOCKED_DRIVER_VERSION', '8.52.322.2202', 'LESS_THAN', '0000-00-00 00:00:00','0000-00-00 00:00:00');

