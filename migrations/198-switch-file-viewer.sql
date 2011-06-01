INSERT INTO waffle_switch (name, active) VALUES ('zamboni-file-viewer', 1) ON DUPLICATE KEY UPDATE active = 1;
