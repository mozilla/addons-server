TRUNCATE perf_results;
ALTER TABLE perf_results ADD UNIQUE (addon_id, appversion_id, osversion_id);
