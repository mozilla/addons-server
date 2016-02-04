DELETE FROM waffle_flag_mkt WHERE name='no-redis';
DELETE FROM waffle_flag_amo WHERE name='no-redis';


INSERT INTO waffle_switch_mkt (name, active) VALUES ('no-redis', 0);
INSERT INTO waffle_switch_amo (name, active) VALUES ('no-redis', 0);
