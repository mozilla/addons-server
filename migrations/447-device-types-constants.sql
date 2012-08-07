ALTER TABLE `addons_devicetypes` ADD COLUMN `device_type` integer UNSIGNED NOT NULL;
UPDATE `addons_devicetypes` SET `device_type` = `device_type_id`;
ALTER TABLE `addons_devicetypes` DROP FOREIGN KEY `device_type_id_refs_id_4d64c634`;
DELETE FROM translations where id in (SELECT `name` FROM `devicetypes`);
DROP TABLE `devicetypes`;
