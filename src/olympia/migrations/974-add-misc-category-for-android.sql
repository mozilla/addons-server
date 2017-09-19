-- Remove old Marketplace categories (they should not be used anymore and we
-- want one of the ids). 11 is the old type used for Web Apps.
DELETE FROM categories WHERE addontype_id = 11;

-- Insert new category. All fields need to match what's in the constants.
-- id is 153
-- addontype_id is 1 (Extension)
-- application_id is 61 (Firefox for Android)
-- weight is 333 (used for sorting)
-- created and modified are NOW (duh!)
-- count is 0 (no addons in it yet)
-- slug is 'other'
-- misc is True (so that the category is used as "My add-on does not fit in any of the categories" in devhub)
INSERT INTO categories (id, addontype_id, application_id, weight, created, modified, count, slug, misc)
VALUES (153, 1, 61, 333, NOW(), NOW(), 0, 'other', true);
