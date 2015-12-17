DROP TABLE `perf_results`;
ALTER TABLE `addons` DROP COLUMN `ts_slowness`;
DELETE FROM `waffle_flag` WHERE `name` = 'perf-tests';
