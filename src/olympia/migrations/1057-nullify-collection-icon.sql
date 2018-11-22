-- Make the icontype column nullable, preparing for its removal later.
ALTER TABLE `collections` MODIFY COLUMN `icontype` varchar(25);
