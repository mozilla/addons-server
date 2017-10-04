-- Insert new category. All fields need to match what's in the constants.
-- id has to be set so it matches our constants. I used +200 the persona categories.
-- addontype_id is 10 (Static Theme)
-- application_id is 1 (Firefox)
-- weight is 0 for normal categories and 333 for 'other' (used for sorting)
-- created and modified are NOW
-- count is 0 (no addons in it yet)
-- slug is the same as the persona slug
-- misc is False, apart from for 'other' (so that the category is used as "My add-on does not fit in any of the categories" in devhub)
INSERT INTO categories (id, addontype_id, application_id, weight, created, modified, count, slug, misc)
VALUES
    (300, 10, 1, 0, NOW(), NOW(), 0, 'abstract', false),
    (320, 10, 1, 0, NOW(), NOW(), 0, 'causes', false),
    (324, 10, 1, 0, NOW(), NOW(), 0, 'fashion', false),
    (326, 10, 1, 0, NOW(), NOW(), 0, 'film-and-tv', false),
    (308, 10, 1, 0, NOW(), NOW(), 0, 'firefox', false),
    (310, 10, 1, 0, NOW(), NOW(), 0, 'foxkeh', false),
    (328, 10, 1, 0, NOW(), NOW(), 0, 'holiday', false),
    (322, 10, 1, 0, NOW(), NOW(), 0, 'music', false),
    (302, 10, 1, 0, NOW(), NOW(), 0, 'nature', false),
    (314, 10, 1, 0, NOW(), NOW(), 333, 'other', true),
    (306, 10, 1, 0, NOW(), NOW(), 0, 'scenery', false),
    (312, 10, 1, 0, NOW(), NOW(), 0, 'seasonal', false),
    (318, 10, 1, 0, NOW(), NOW(), 0, 'solid', false),
    (304, 10, 1, 0, NOW(), NOW(), 0, 'sports', false),
    (316, 10, 1, 0, NOW(), NOW(), 0, 'websites', false);
