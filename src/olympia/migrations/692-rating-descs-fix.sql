ALTER TABLE webapps_rating_descriptors
    ADD COLUMN `has_classind_nudity` bool NOT NULL,
    DROP COLUMN `has_classind_sexual_content`;
