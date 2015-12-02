# It seems the constraint name for the `backup_version` column differs between the local and dev/stage/prod servers.
# We thus need some hackery to find its name, and remove it dynamically.
#
# First get the constraint name.
SET @CONSTRAINT_NAME := (select CONSTRAINT_NAME from information_schema.key_column_usage where TABLE_NAME="addons" and COLUMN_NAME="backup_version");

# Then remove it.
SET @QUERY = CONCAT('ALTER TABLE addons DROP FOREIGN KEY ', @constraint_name, ';');
PREPARE stmt FROM @QUERY;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

# Finally drop the column.
ALTER TABLE `addons` DROP COLUMN `backup_version`;
