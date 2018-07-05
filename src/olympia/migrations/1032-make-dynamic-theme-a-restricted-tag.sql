INSERT INTO tags (tag_text, denied, restricted)
VALUES ('dynamic theme', 0, 1) ON DUPLICATE KEY UPDATE restricted = 1;
