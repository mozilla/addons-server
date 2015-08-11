ALTER TABLE
    `files`
ADD COLUMN
    `original_hash` varchar(255) NOT NULL DEFAULT ''
;

UPDATE
    `files`
SET
    `original_hash` = `hash`
WHERE
    `original_hash` = '' AND `hash` IS NOT NULL
;
