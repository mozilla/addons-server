DROP PROCEDURE IF EXISTS drop_addons_col_if_exists;

DELIMITER ';;'

CREATE PROCEDURE drop_addons_col_if_exists() BEGIN
    /* drop the known latest version foreign keys if they exist */
    IF EXISTS (SELECT * FROM information_schema.table_constraints WHERE table_schema = (SELECT DATABASE()) AND table_name = 'addons' AND constraint_name = 'latest_version_refs_versions') THEN
        ALTER TABLE addons drop foreign key latest_version_refs_versions;
    END IF;
    IF EXISTS (SELECT * FROM information_schema.table_constraints WHERE table_schema = (SELECT DATABASE()) AND table_name = 'addons' AND constraint_name = 'latest_version_refs_id_46aa95ab') THEN
        ALTER TABLE addons drop foreign key latest_version_refs_id_46aa95ab;
    END IF;

    /* drop the columns if they exist */
    IF EXISTS (SELECT * FROM information_schema.columns WHERE table_schema = (SELECT DATABASE()) AND table_name = 'addons' AND column_name = 'latest_version') THEN
        ALTER TABLE addons drop column latest_version;
    END IF;
    IF EXISTS (SELECT * FROM information_schema.columns WHERE table_schema = (SELECT DATABASE()) AND table_name = 'addons' AND column_name = 'sitespecific') THEN
        ALTER TABLE addons drop column sitespecific;
    END IF;
    IF EXISTS (SELECT * FROM information_schema.columns WHERE table_schema = (SELECT DATABASE()) AND table_name = 'addons' AND column_name = 'is_listed') THEN
        ALTER TABLE addons drop column is_listed;
    END IF;
END;;

DELIMITER ';'

CALL drop_addons_col_if_exists();

DROP PROCEDURE IF EXISTS drop_addons_col_if_exists;
