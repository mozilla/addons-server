CREATE INDEX created_idx ON addons (created);
CREATE INDEX modified_idx ON addons (modified);
CREATE INDEX weeklydownloads_idx ON addons (weeklydownloads);

CREATE INDEX rating_type_idx ON addons (bayesianrating, addontype_id);
CREATE INDEX created_type_idx ON addons (created, addontype_id);
CREATE INDEX modified_type_idx ON addons (modified, addontype_id);
CREATE INDEX downloads_type_idx ON addons (weeklydownloads, addontype_id);
CREATE INDEX last_updated_type_idx ON addons (last_updated, addontype_id);

CREATE INDEX addon_user_listed_idx ON addons_users (addon_id, user_id, listed);
CREATE INDEX type_status_inactive_idx ON addons (addontype_id, status, inactive);

CREATE INDEX blacklisted_idx ON tags (blacklisted);
CREATE INDEX tag_num_addons_idx ON tag_stat (tag_id, num_addons);

CREATE INDEX addon_listed_idx ON addons_users (addon_id, listed);
