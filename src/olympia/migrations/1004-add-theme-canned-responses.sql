-- type = 2 was previously used for webapp canned responses.
DELETE FROM `cannedresponses` WHERE type = 2;

-- sort_group is one of the `actions[]` keys from ReviewHelper
-- type is now CANNED_RESPONSE_THEME = 2

INSERT INTO `cannedresponses` (name, response, sort_group, type, created, modified)
VALUES
    ('Approved', 'Approved!', 'public', 2, NOW(), NOW()),
    ('1. Sexual or pornographic content', 'Sexual or pornographic content', 'reject', 2, NOW(), NOW()),
    ('2. Inappropriate or offensive content', 'Inappropriate or offensive content', 'reject', 2, NOW(), NOW()),
    ('3. Violence, war, or weaponry images', 'Violence, war, or weaponry images', 'reject', 2, NOW(), NOW()),
    ('4. Nazi or other hate content', 'Nazi or other hate content', 'reject', 2, NOW(), NOW()),
    ('5. Defamatory content', 'Defamatory content', 'reject', 2, NOW(), NOW()),
    ('6. Online gambling', 'Online gambling', 'reject', 2, NOW(), NOW()),
    ('7. Spam content', 'Spam content', 'reject', 2, NOW(), NOW()),
    ('8. Low-quality, stretched, or blank image', 'Low-quality, stretched, or blank image', 'reject', 2, NOW(), NOW()),
    ('9. Header image alignment problem', 'Header image alignment problem', 'reject', 2, NOW(), NOW())
;
