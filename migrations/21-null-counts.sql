ALTER TABLE personas
    CHANGE COLUMN `popularity` `popularity` int(11) NOT NULL default 0;

ALTER TABLE addons
    CHANGE COLUMN `totalreviews` `totalreviews` int(11) NOT NULL default 0;
