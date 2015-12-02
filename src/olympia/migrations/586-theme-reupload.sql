DROP TABLE IF EXISTS `rereview_queue_theme`;
CREATE TABLE `rereview_queue_theme` (
    `id` int(11) unsigned NOT NULL auto_increment,
    `theme_id` int(11) unsigned NOT NULL,
    `footer` varchar(72) NOT NULL,
    `header` varchar(72) NOT NULL,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

ALTER TABLE `rereview_queue_theme`
    ADD CONSTRAINT FOREIGN KEY (`theme_id`) REFERENCES `personas` (`id`)
    ON DELETE CASCADE;
