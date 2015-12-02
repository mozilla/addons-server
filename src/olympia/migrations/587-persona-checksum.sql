ALTER TABLE `personas`
    ADD COLUMN `checksum` varchar(64) NOT NULL DEFAULT '',
    ADD COLUMN `dupe_persona_id` int(11) UNSIGNED NULL,
    ADD CONSTRAINT `dupe_persona_id_refs_id` FOREIGN KEY (`dupe_persona_id`)
        REFERENCES `personas` (`id`);

CREATE INDEX personas_checksum_index ON personas (checksum);

ALTER TABLE `rereview_queue_theme`
    ADD COLUMN `dupe_persona_id` int(11) UNSIGNED NULL,
    ADD CONSTRAINT `rqt_dupe_persona_id_refs_id` FOREIGN KEY (`dupe_persona_id`)
        REFERENCES `personas` (`id`);

