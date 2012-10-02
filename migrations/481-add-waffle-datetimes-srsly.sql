UPDATE `waffle_flag_amo` set `created` = NOW() where `created` = 0;
UPDATE `waffle_flag_amo` set `modified` = NOW() where `created` = 0;

UPDATE `waffle_sample_amo` set `created` = NOW() where `created` = 0;
UPDATE `waffle_sample_amo` set `modified` = NOW() where `created` = 0;

UPDATE `waffle_switch_amo` set `created` = NOW() where `created` = 0;
UPDATE `waffle_switch_amo` set `modified` = NOW() where `created` = 0;

UPDATE `waffle_flag_mkt` set `created` = NOW() where `created` = 0;
UPDATE `waffle_flag_mkt` set `modified` = NOW() where `created` = 0;

UPDATE `waffle_sample_mkt` set `created` = NOW() where `created` = 0;
UPDATE `waffle_sample_mkt` set `modified` = NOW() where `created` = 0;

UPDATE `waffle_switch_mkt` set `created` = NOW() where `created` = 0;
UPDATE `waffle_switch_mkt` set `modified` = NOW() where `created` = 0;



