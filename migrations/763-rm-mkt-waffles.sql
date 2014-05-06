DROP TABLE IF EXISTS waffle_flag_mkt_groups;
DROP TABLE IF EXISTS waffle_flag_mkt_users;
DROP TABLE IF EXISTS waffle_flag_mkt;
DROP TABLE IF EXISTS waffle_sample_mkt;
DROP TABLE IF EXISTS waffle_switch_mkt;

DELETE FROM waffle_sample_amo WHERE name='paypal-disabled-limit';

DELETE FROM waffle_switch_amo WHERE name='paypal-disable';
