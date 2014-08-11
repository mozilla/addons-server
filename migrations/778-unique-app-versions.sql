ALTER TABLE
    `appversions`
ADD CONSTRAINT
    UNIQUE (`application_id`, `version`);
