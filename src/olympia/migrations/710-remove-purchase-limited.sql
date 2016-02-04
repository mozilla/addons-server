DELETE FROM waffle_flag_mkt_users WHERE flag_id = (SELECT id FROM waffle_flag_mkt WHERE name = 'override-app-purchase');
DELETE FROM waffle_flag_mkt_groups WHERE flag_id = (SELECT id FROM waffle_flag_mkt WHERE name = 'override-app-purchase');
DELETE FROM waffle_flag_mkt WHERE name = 'override-app-purchase';
