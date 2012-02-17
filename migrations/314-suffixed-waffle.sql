CREATE TABLE waffle_flag_amo LIKE waffle_flag;
CREATE TABLE waffle_flag_amo_users LIKE waffle_flag_users;
CREATE TABLE waffle_flag_amo_groups LIKE waffle_flag_groups;
CREATE TABLE waffle_switch_amo LIKE waffle_switch;
CREATE TABLE waffle_sample_amo LIKE waffle_sample;
CREATE TABLE waffle_flag_mkt LIKE waffle_flag;
CREATE TABLE waffle_flag_mkt_users LIKE waffle_flag_users;
CREATE TABLE waffle_flag_mkt_groups LIKE waffle_flag_groups;
CREATE TABLE waffle_switch_mkt LIKE waffle_switch;
CREATE TABLE waffle_sample_mkt LIKE waffle_sample;

INSERT INTO waffle_flag_amo SELECT * FROM waffle_flag;
INSERT INTO waffle_flag_amo_users SELECT * FROM waffle_flag_users;
INSERT INTO waffle_flag_amo_groups SELECT * FROM waffle_flag_groups;
INSERT INTO waffle_switch_amo SELECT * FROM waffle_switch;
INSERT INTO waffle_sample_amo SELECT * FROM waffle_sample;

INSERT INTO waffle_flag_mkt SELECT * FROM waffle_flag;
INSERT INTO waffle_flag_mkt_users SELECT * FROM waffle_flag_users;
INSERT INTO waffle_flag_mkt_groups SELECT * FROM waffle_flag_groups;
INSERT INTO waffle_switch_mkt SELECT * FROM waffle_switch;
INSERT INTO waffle_sample_mkt SELECT * FROM waffle_sample;
