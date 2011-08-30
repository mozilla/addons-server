ALTER TABLE addons_dependencies ADD UNIQUE (addon_id, dependent_addon_id);
