-- Remove categories for applications others than Firefox and Firefox for
-- Android.
-- Removing those categories and associated m2m will hide them from the site,
-- and prevent developers from choosing them when submitting new add-ons or
-- editing details for an existing one.
DELETE addons_categories FROM addons_categories
    INNER JOIN categories
    ON addons_categories.category_id=categories.id
    WHERE categories.application_id NOT IN (1, 61);
DELETE FROM categories WHERE application_id NOT IN (1, 61);
