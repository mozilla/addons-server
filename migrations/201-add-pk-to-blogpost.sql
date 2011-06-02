ALTER TABLE blogposts
    ADD COLUMN id INTEGER UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY FIRST,
    ADD COLUMN `modified` datetime NOT NULL default '0000-00-00 00:00:00',
    ADD COLUMN `created` datetime NOT NULL default '0000-00-00 00:00:00';

UPDATE blogposts SET modified=date_posted, created=date_posted;

