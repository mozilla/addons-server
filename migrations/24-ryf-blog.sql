CREATE TABLE `blog_cache_ryf` (
    `id` int(11) unsigned NOT NULL auto_increment,
    `title` VARCHAR(255) NOT NULL default '',
    `excerpt` text,
    `permalink` varchar(255) not null default '',
    `image` varchar(255) not null default '',
    `date_posted` datetime,
    PRIMARY KEY  (`id`)
) DEFAULT CHARSET=utf8;
