INSERT INTO waffle_sample (name, percent, note)
VALUES ('paypal-disabled-limit', 10.0, 'Sanity check limit on paypal cron');

INSERT INTO waffle_switch (name, active, note)
VALUES ('paypal-disable', 0, 'Actually disable addons from paypal cron');
