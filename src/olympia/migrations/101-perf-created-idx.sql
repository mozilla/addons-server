CREATE INDEX addon_created_idx ON perf_results (addon_id, created);

ALTER TABLE addons
    ADD COLUMN ts_slowness FLOAT NULL;

CREATE INDEX ts_slowness_idx ON addons (ts_slowness);
