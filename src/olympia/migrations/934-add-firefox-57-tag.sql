INSERT INTO tags (tag_text, denied, restricted, num_addons, created, modified) VALUES ('firefox57', 0, 1, 0, NOW(), NOW()) ON DUPLICATE KEY UPDATE restricted = 1;
