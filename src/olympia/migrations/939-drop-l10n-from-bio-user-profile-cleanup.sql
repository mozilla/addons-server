/* Follow-on from migration 938 -
Drop the (now obsolete) bio and old translations. */

DROP PROCEDURE IF EXISTS drop_bio_fk;

DELIMITER ';;'

CREATE PROCEDURE drop_bio_fk() BEGIN
    /* drop the bio foreign key so we can clear the translations.
    - we know prod and local dbs have different keys, so try to handle both */

    /* prod fk name */
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE table_schema = (SELECT DATABASE()) AND table_name = 'users' AND constraint_name = 'users_ibfk_1') THEN
        ALTER TABLE reviews DROP FOREIGN KEY users_ibfk_1;
    END IF;

    /* local docker default fk name */
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE table_schema = (SELECT DATABASE()) AND table_name = 'users' AND constraint_name = 'users_bio_21cc3d1ebf26e19_fk_translations_id') THEN
        ALTER TABLE reviews DROP FOREIGN KEY users_bio_21cc3d1ebf26e19_fk_translations_id;
    END IF;
END;;

DELIMITER ';'

CALL drop_bio_fk();

DROP PROCEDURE IF EXISTS drop_bio_fk;

/* Clear out the translations. */
DELETE FROM `translations` WHERE `id` in (SELECT `bio` FROM `users`);

/* Drop the old columns. */
ALTER TABLE `users`
    DROP COLUMN `bio`,
    DROP COLUMN lang,
    DROP COLUMN region;
