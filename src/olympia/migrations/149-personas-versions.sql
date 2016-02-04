-- Create a version row for each persona.
INSERT INTO versions (addon_id, version, created, modified)
    SELECT addons.id, 0, NOW(), NOW()
    FROM addons LEFT JOIN versions
      ON addons.id=versions.addon_id
    WHERE versions.id IS NULL;

-- Attach the current version for personas missing a current_version.
UPDATE addons INNER JOIN
  (SELECT addons.id AS addon_id, versions.id AS version_id
   FROM addons INNER JOIN versions
   ON (addons.id = versions.addon_id
       AND addons.addontype_id = 9
       AND addons.current_version IS NULL)
  ) AS J ON (addons.id = J.addon_id)
SET addons.current_version = J.version_id;
