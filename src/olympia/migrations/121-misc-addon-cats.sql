ALTER TABLE categories
    ADD COLUMN misc tinyint(1) UNSIGNED NOT NULL DEFAULT '0';

UPDATE categories SET misc=1 WHERE slug IN ('miscellaneous', 'other');
