/* If this migration fails locally, comment lines for columns that don't exist */
ALTER TABLE `files`
 DROP COLUMN `is_packaged`,
 DROP COLUMN `jetpack_version`,
 DROP COLUMN `requires_chrome`,
 DROP COLUMN `is_multi_package`;
