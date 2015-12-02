-- Addon dates should not be zero.
UPDATE addons
    SET modified=created
    WHERE modified = 0;

UPDATE addons
    SET last_updated=created
    WHERE last_updated=0;
