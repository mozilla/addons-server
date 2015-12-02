CREATE TABLE `stats_firefoxcup` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `created` datetime NOT NULL,
  `modified` datetime NOT NULL,
  `persona_id` int(10) unsigned NOT NULL,
  `popularity` int(10) unsigned NOT NULL,
  PRIMARY KEY (`id`),
  KEY `firefoxcup_popularityhistory_persona_id` (`persona_id`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;
