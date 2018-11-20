-- Insert new category. All fields need to match what's in the constants.
-- id has to be set so it matches our constants. I used +100 the desktop categories.
-- addontype_id is 10 (Static Theme)
-- application_id is 61 (Firefox for Android)
-- weight is 0 for normal categories and 333 for 'other' (used for sorting)
-- created and modified are NOW
-- count is 0 (no addons in it yet)
-- slug is the same as the persona slug
-- misc is False, apart from for 'other' (so that the category is used as "My add-on does not fit in any of the categories" in devhub)
INSERT INTO categories (id, addontype_id, application_id, weight, created, modified, count, slug, misc)
VALUES
    (400, 10, 61, 0, NOW(), NOW(), 0, 'abstract', false),
    (420, 10, 61, 0, NOW(), NOW(), 0, 'causes', false),
    (424, 10, 61, 0, NOW(), NOW(), 0, 'fashion', false),
    (426, 10, 61, 0, NOW(), NOW(), 0, 'film-and-tv', false),
    (408, 10, 61, 0, NOW(), NOW(), 0, 'firefox', false),
    (410, 10, 61, 0, NOW(), NOW(), 0, 'foxkeh', false),
    (428, 10, 61, 0, NOW(), NOW(), 0, 'holiday', false),
    (422, 10, 61, 0, NOW(), NOW(), 0, 'music', false),
    (402, 10, 61, 0, NOW(), NOW(), 0, 'nature', false),
    (414, 10, 61, 0, NOW(), NOW(), 333, 'other', true),
    (406, 10, 61, 0, NOW(), NOW(), 0, 'scenery', false),
    (412, 10, 61, 0, NOW(), NOW(), 0, 'seasonal', false),
    (418, 10, 61, 0, NOW(), NOW(), 0, 'solid', false),
    (404, 10, 61, 0, NOW(), NOW(), 0, 'sports', false),
    (416, 10, 61, 0, NOW(), NOW(), 0, 'websites', false);
