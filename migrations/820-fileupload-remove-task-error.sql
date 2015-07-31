-- Update any old file upload entries which have errors to
-- include a skeleton system error validator report.
UPDATE
    `file_uploads`
SET
    `validation` = '{"errors": 1, "success": false, "messages": [{"description": ["Validation was unable to complete successfully due to an unexpected error.", "The error has been logged, but please consider filing an issue report here: http://mzl.la/1DG0sFd"], "type": "error", "id": ["validator", "unexpected_exception"], "tier": 1, "for_appversions": null, "message": "An unexpected error has occurred.", "uid": "35432f419340461897aa8362398339c4"}], "metadata": {}}',
    `valid` = FALSE
WHERE
    `validation` IS NULL AND `task_error` IS NOT NULL
;

ALTER TABLE
    `file_uploads`
DROP COLUMN
    `task_error` BOOL DEFAULT FALSE
;
