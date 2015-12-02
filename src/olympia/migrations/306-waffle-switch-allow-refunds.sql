INSERT INTO waffle_switch (name, active, note) VALUES ('allow-refund', 0, 'Allow refund of paypal payments');
DELETE FROM waffle_flag WHERE name='allow-refund';
