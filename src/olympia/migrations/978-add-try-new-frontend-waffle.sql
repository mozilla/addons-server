INSERT INTO waffle_switch (name, active, created, modified, note) VALUES ('try-new-frontend', 0, NOW(), NOW(), 'Display notification to try the new frontend') ON DUPLICATE KEY UPDATE active = 0;
