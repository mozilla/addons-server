INSERT INTO waffle_switch (name, active, note) VALUES ('browserid-login', 0, "Support for BrowserID login." ) ON DUPLICATE KEY UPDATE active = 0;
