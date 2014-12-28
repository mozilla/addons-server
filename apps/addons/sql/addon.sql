-- These are all the indexes you really need to run olympia. They're explicitly
-- used in queries. We drop them all in one file because that's easy.

CREATE INDEX downloads_type_idx ON addons (weeklydownloads, addontype_id);
CREATE INDEX created_type_idx ON addons (created, addontype_id);
CREATE INDEX rating_type_idx ON addons (bayesianrating, addontype_id);
CREATE INDEX last_updated_type_idx ON addons (last_updated, addontype_id);
CREATE INDEX type_status_inactive_idx ON addons (addontype_id, status, inactive);
CREATE INDEX adus_type_idx ON addons (average_daily_users, addontype_id);
