-- bug 592168
INSERT INTO users_tags_addons (user_id, tag_id, addon_id, created)
    SELECT '9945',  '119', addon_id, NOW() FROM addons_categories WHERE category_id=92;

DELETE FROM addons_categories WHERE category_id=92;

DELETE FROM categories WHERE id=92;
