CREATE INDEX feature_addon_idx ON addons_categories (feature, addon_id);

-- This index is redundant.
ALTER TABLE addons_categories DROP KEY tag_id;
