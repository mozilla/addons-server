-- We only show categories with weight >= 0.  We want search categories to
-- show up in the bottom list, so we hide them from the top category list.

-- These are the search categories for Firefox and Seamonkey.
UPDATE categories SET weight=-1 WHERE id IN (13, 47);
