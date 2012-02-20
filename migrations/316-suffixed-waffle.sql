ALTER TABLE waffle_flag RENAME TO waffle_flag_amo;
ALTER TABLE waffle_flag_users RENAME TO waffle_flag_amo_users;
ALTER TABLE waffle_flag_groups RENAME TO waffle_flag_amo_groups;
ALTER TABLE waffle_switch RENAME TO waffle_switch_amo;
ALTER TABLE waffle_sample RENAME TO waffle_sample_amo;
CREATE TABLE waffle_flag_mkt LIKE waffle_flag_amo;
CREATE TABLE waffle_flag_mkt_users LIKE waffle_flag_amo_users;
CREATE TABLE waffle_flag_mkt_groups LIKE waffle_flag_amo_groups;
CREATE TABLE waffle_switch_mkt LIKE waffle_switch_amo;
CREATE TABLE waffle_sample_mkt LIKE waffle_sample_amo;


INSERT INTO waffle_flag_mkt SELECT * FROM waffle_flag_amo;
INSERT INTO waffle_flag_mkt_users SELECT * FROM waffle_flag_amo_users;
INSERT INTO waffle_flag_mkt_groups SELECT * FROM waffle_flag_amo_groups;
INSERT INTO waffle_switch_mkt SELECT * FROM waffle_switch_amo;
INSERT INTO waffle_sample_mkt SELECT * FROM waffle_sample_amo;
