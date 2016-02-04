ALTER TABLE users
    ADD COLUMN `t_shirt_requested` datetime DEFAULT NULL;

INSERT IGNORE INTO
    waffle_switch (name, active, created, modified, note)
VALUES
    ('t-shirt-orders', 1, NOW(), NOW(), 'Accept special edition add-ons t-shirt requests.');
