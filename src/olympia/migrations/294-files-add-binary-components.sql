ALTER TABLE `files` ADD COLUMN `binary_components` bool NOT NULL DEFAULT '0';
CREATE INDEX `files_cedd2560` ON `files` (`binary_components`);
