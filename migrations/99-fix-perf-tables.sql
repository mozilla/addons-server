-- we need to allow nulls for the baseline numbers
ALTER TABLE `perf_results` CHANGE `addon_id` `addon_id` INT( 11 ) UNSIGNED NULL;
