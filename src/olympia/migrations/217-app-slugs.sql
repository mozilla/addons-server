ALTER TABLE addons
  ADD COLUMN `app_slug` varchar(30) default NULL,
  ADD CONSTRAINT UNIQUE KEY `app_slug` (`app_slug`);
