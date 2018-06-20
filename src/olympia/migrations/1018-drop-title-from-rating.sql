/* Drop rating title */

SET @CONSTRAINT_NAME := (SELECT CONSTRAINT_NAME FROM information_schema.key_column_usage WHERE TABLE_SCHEMA=(SELECT DATABASE()) AND TABLE_NAME="reviews" and COLUMN_NAME="title" AND REFERENCED_TABLE_NAME = "translations");

SET @QUERY = CONCAT('ALTER TABLE reviews DROP FOREIGN KEY ', @constraint_name, ';');
PREPARE stmt FROM @QUERY;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

/* Ignore the translations because our databases are a bag of crazy. */

/* Drop the old column. */
ALTER TABLE `reviews`
    DROP COLUMN `title`;
