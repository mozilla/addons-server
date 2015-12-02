ALTER TABLE webapps_geodata
    ADD COLUMN `region_br_iarc_exclude` bool NOT NULL DEFAULT false,
    ADD COLUMN `region_de_iarc_exclude` bool NOT NULL DEFAULT false;
