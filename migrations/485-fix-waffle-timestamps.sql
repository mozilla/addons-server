-- From now on, don't forget to set timestamps in your waffle migrations!

update waffle_flag_amo set modified = now(), created = now();
update waffle_sample_amo set modified = now(), created = now();
update waffle_switch_amo set modified = now(), created = now();

update waffle_flag_mkt set modified = now(), created = now();
update waffle_sample_mkt set modified = now(), created = now();
update waffle_switch_mkt set modified = now(), created = now();
