-- Before bug 647769 was fixed, versions for unreviewed addons where
-- getting created with NULL nomination dates.

CREATE TEMPORARY TABLE versions_fix (nomination DATETIME, addon_id INT(11))
        SELECT old_v.nomination, old_v.addon_id
        FROM versions v
        JOIN addons a on a.id=v.addon_id
        JOIN files f on f.version_id=v.id
        JOIN versions old_v on old_v.addon_id=a.id
        WHERE a.status IN (3,9) and v.nomination IS NULL
        and f.status <> 7 and old_v.nomination is not NULL;

UPDATE versions v
    JOIN addons a on a.id=v.addon_id
    JOIN files f on f.version_id=v.id
    SET v.nomination = (SELECT  nomination FROM versions_fix
                        WHERE addon_id = a.id
                        ORDER BY nomination DESC LIMIT 1)
    WHERE a.status IN (3,9) and v.nomination is NULL and f.status <> 7;
