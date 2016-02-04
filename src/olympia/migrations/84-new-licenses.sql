ALTER TABLE licenses
    ADD COLUMN `url` varchar(200),
    ADD COLUMN `builtin` integer UNSIGNED NOT NULL DEFAULT 0,
    ADD COLUMN `on_form` bool NOT NULL DEFAULT false,
    ADD COLUMN `some_rights` bool NOT NULL DEFAULT false,
    ADD COLUMN `icons` varchar(255);

UPDATE licenses SET builtin=(name + 1) WHERE name <> -1;

ALTER TABLE licenses
    DROP COLUMN `name`;

ALTER TABLE licenses
    ADD COLUMN `name` int(11) UNSIGNED,
    ADD CONSTRAINT FOREIGN KEY (`name`) REFERENCES `translations` (`id`);

CREATE INDEX builtin_idx ON licenses (builtin);
