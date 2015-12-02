DROP TABLE IF EXISTS `stats_collections_share_counts`;
CREATE TABLE `stats_collections_share_counts` (
  `id` int(11) unsigned NOT NULL AUTO_INCREMENT,
  `collection_id` int(11) unsigned NOT NULL DEFAULT '0',
  `count` int(11) unsigned NOT NULL DEFAULT '0',
  `service` varchar(128) DEFAULT NULL,
  `date` date NOT NULL DEFAULT '0000-00-00',
  PRIMARY KEY (`id`),
  UNIQUE KEY (`collection_id`, `service`, `date`),
  CONSTRAINT FOREIGN KEY (collection_id) REFERENCES collections (id),
  KEY `date` (`date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

DROP TABLE IF EXISTS `stats_collections_share_counts_totals`;
CREATE TABLE `stats_collections_share_counts_totals` (
  `id` int(11) unsigned NOT NULL AUTO_INCREMENT,
  `collection_id` int(11) unsigned NOT NULL DEFAULT '0',
  `count` int(11) unsigned NOT NULL DEFAULT '0',
  `service` varchar(128) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY (`collection_id`, `service`),
  CONSTRAINT FOREIGN KEY (collection_id) REFERENCES collections (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
