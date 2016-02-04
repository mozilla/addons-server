ALTER TABLE `waffle_flag_amo` ADD COLUMN `testing` bool NOT NULL;
ALTER TABLE `waffle_flag_amo` ADD COLUMN `languages` longtext NOT NULL;
ALTER TABLE `waffle_flag_amo` ADD COLUMN `created` datetime NOT NULL;
ALTER TABLE `waffle_flag_amo` ADD COLUMN `modified` datetime NOT NULL;

ALTER TABLE `waffle_sample_amo` ADD COLUMN `created` datetime NOT NULL;
ALTER TABLE `waffle_sample_amo` ADD COLUMN `modified` datetime NOT NULL;

ALTER TABLE `waffle_switch_amo` ADD COLUMN `created` datetime NOT NULL;
ALTER TABLE `waffle_switch_amo` ADD COLUMN `modified` datetime NOT NULL;


ALTER TABLE `waffle_flag_mkt` ADD COLUMN `testing` bool NOT NULL;
ALTER TABLE `waffle_flag_mkt` ADD COLUMN `languages` longtext NOT NULL;
ALTER TABLE `waffle_flag_mkt` ADD COLUMN `created` datetime NOT NULL;
ALTER TABLE `waffle_flag_mkt` ADD COLUMN `modified` datetime NOT NULL;

ALTER TABLE `waffle_sample_mkt` ADD COLUMN `created` datetime NOT NULL;
ALTER TABLE `waffle_sample_mkt` ADD COLUMN `modified` datetime NOT NULL;

ALTER TABLE `waffle_switch_mkt` ADD COLUMN `created` datetime NOT NULL;
ALTER TABLE `waffle_switch_mkt` ADD COLUMN `modified` datetime NOT NULL;
