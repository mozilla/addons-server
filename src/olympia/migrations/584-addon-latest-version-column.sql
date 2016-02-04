ALTER TABLE
    `addons`
ADD COLUMN
    `latest_version` int(11) unsigned DEFAULT NULL,
ADD CONSTRAINT
    `latest_version_refs_versions`
    FOREIGN KEY (`latest_version`) REFERENCES `versions` (`id`)
    ON DELETE SET NULL;

UPDATE
    addons AS a,
    versions AS v,
    files AS f
SET
    a.latest_version = v.id
WHERE
    NOT EXISTS (SELECT 1
                FROM
                    versions AS v2
                INNER JOIN
                    files AS f ON f.version_id = v2.id
                WHERE
                    v2.addon_id = a.id
                    AND v2.created > v.created
                    AND f.status <> 7) -- BETA
    AND v.addon_id = a.id
    AND f.version_id = v.id
    AND f.status <> 7; -- BETA
