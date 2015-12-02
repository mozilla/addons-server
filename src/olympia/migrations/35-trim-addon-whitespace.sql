-- Cleans out the whitespace
UPDATE translations
SET
    localized_string=TRIM(localized_string),
    localized_string_clean=TRIM(localized_string_clean)
WHERE id IN (SELECT name FROM addons WHERE name IS NOT NULL);

-- ~181 changed in <9s
