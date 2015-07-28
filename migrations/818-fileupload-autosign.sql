ALTER TABLE
    `file_uploads`
DROP COLUMN
    `escaped_validation`
;
ALTER TABLE
    `file_uploads`
ADD COLUMN
    `automated_signing` BOOL DEFAULT FALSE
;
