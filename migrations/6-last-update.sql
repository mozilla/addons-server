ALTER TABLE addons
    ADD COLUMN `last_updated` datetime,
    ADD INDEX `last_updated` (`last_updated`);

-- Populate the new field in SQL the first time for speed.  We'll keep it
-- up to date in a cron job after this.

CREATE TEMPORARY TABLE tmp (
    addon_id INT PRIMARY KEY,
    last_updated datetime
);

-- public add-ons, only count public files
INSERT INTO tmp (
SELECT DISTINCT
    a.id AS id,
    MAX(f.datestatuschanged) AS last_updated
FROM
    addons a INNER JOIN versions v ON (a.id=v.addon_id)
    INNER JOIN files f ON (v.id=f.version_id AND f.status=4)
WHERE
    a.status=4
GROUP BY a.id
);

-- non-public add-ons
INSERT INTO tmp (
SELECT DISTINCT
    a.id AS id,
    MAX(f.created) AS last_updated
FROM
    addons a INNER JOIN versions v ON (a.id=v.addon_id)
    INNER JOIN files f ON (v.id=f.version_id)
WHERE
    a.status IN (0,1,2,3,5,7)
GROUP BY a.id
);

-- listed add-ons
INSERT INTO tmp (
SELECT DISTINCT
    a.id as id,
    v.created AS last_updated
FROM
    addons a INNER JOIN versions v ON (a.id=v.addon_id)
WHERE
    a.status = 6
GROUP BY a.id
);

-- personas
INSERT INTO tmp (
SELECT
    a.id as id,
    a.modified as last_updated
FROM
    addons a
WHERE
    a.addontype_id = 9
);

UPDATE addons INNER JOIN tmp ON (addons.id = tmp.addon_id)
   SET addons.last_updated = tmp.last_updated;

-- Get anything that didn't match above.
UPDATE addons SET last_updated = modified
 WHERE addons.last_updated IS NULL;
