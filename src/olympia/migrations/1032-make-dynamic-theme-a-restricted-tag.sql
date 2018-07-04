INSERT INTO tags (tag_text, blacklisted, restricted)
VALUES ('dynamic theme', 0, 1) ON DUPLICATE KEY UPDATE restricted = 1;
