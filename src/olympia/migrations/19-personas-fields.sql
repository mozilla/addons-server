ALTER TABLE personas
    ADD COLUMN `movers` double precision,
    ADD COLUMN `popularity` integer,
    ADD COLUMN `license_id` int(11) unsigned,
    ADD CONSTRAINT FOREIGN KEY (`license_id`) REFERENCES `licenses` (`id`);
