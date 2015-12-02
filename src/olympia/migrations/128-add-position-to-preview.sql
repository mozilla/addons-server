ALTER TABLE previews
    ADD COLUMN position TINYINT(11) unsigned DEFAULT 0 AFTER highlight;

CREATE INDEX addon_position_created_idx
    ON previews (`addon_id`, `position`, `created`);

UPDATE previews
    SET position=1 WHERE highlight=0;

ALTER TABLE previews
    DROP COLUMN highlight;


