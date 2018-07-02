ALTER TABLE `version_previews`
    ADD COLUMN position TINYINT(11) unsigned DEFAULT 0;

CREATE INDEX version_position_created_idx
    ON version_previews (`version_id`, `position`, `created`);
