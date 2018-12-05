UPDATE `collections` SET `collections`.`uuid` = REPLACE(`collections`.`uuid`, '-', '');
ALTER TABLE `collections`
  MODIFY COLUMN `uuid` char(32) DEFAULT NULL;
