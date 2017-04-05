DROP PROCEDURE IF EXISTS drop_client_data_cols;

DELIMITER ';;'

CREATE PROCEDURE drop_client_data_cols() BEGIN
    /* drop the client_data foreign keys - since the fks have 2 possible names each, look them up in information_schema */
    /* reviews */
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE table_schema = (SELECT DATABASE()) AND table_name = 'reviews' AND constraint_name = 'client_data_id_refs_id_c0e106c0') THEN
        ALTER TABLE reviews DROP FOREIGN KEY client_data_id_refs_id_c0e106c0;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE table_schema = (SELECT DATABASE()) AND table_name = 'reviews' AND constraint_name = 'client_data_id_refs_id_d160c5ba') THEN
        ALTER TABLE reviews DROP FOREIGN KEY client_data_id_refs_id_d160c5ba;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE table_schema = (SELECT DATABASE()) AND table_name = 'reviews' AND constraint_name = 'reviews_client_data_id_1047afc43ee763e7_fk_client_data_id') THEN
        ALTER TABLE reviews DROP FOREIGN KEY reviews_client_data_id_1047afc43ee763e7_fk_client_data_id;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = (SELECT DATABASE()) AND table_name = 'reviews' AND column_name = 'client_data_id') THEN
        ALTER TABLE reviews DROP COLUMN client_data_id;
    END IF;

    /* stats_contributions */
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE table_schema = (SELECT DATABASE()) AND table_name = 'stats_contributions' AND constraint_name = 'client_data_id_refs_id_d3f47e0e') THEN
        ALTER TABLE stats_contributions DROP FOREIGN KEY client_data_id_refs_id_d3f47e0e;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE table_schema = (SELECT DATABASE()) AND table_name = 'stats_contributions' AND constraint_name = 'client_data_id_refs_id_c8ef1728') THEN
        ALTER TABLE stats_contributions DROP FOREIGN KEY client_data_id_refs_id_c8ef1728;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE table_schema = (SELECT DATABASE()) AND table_name = 'reviews' AND constraint_name = 'stats_contribu_client_data_id_3a5cd4151b258907_fk_client_data_id') THEN
        ALTER TABLE stats_contributions DROP FOREIGN KEY stats_contribu_client_data_id_3a5cd4151b258907_fk_client_data_id;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = (SELECT DATABASE()) AND table_name = 'stats_contributions' AND column_name = 'client_data_id') THEN
        ALTER TABLE stats_contributions DROP COLUMN client_data_id;
    END IF;
END;;

DELIMITER ';'

CALL drop_client_data_cols();

DROP TABLE IF EXISTS `client_data`;

DROP PROCEDURE IF EXISTS drop_client_data_cols;
