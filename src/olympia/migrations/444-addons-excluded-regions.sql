CREATE TABLE addons_excluded_regions (
    id int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    created datetime NOT NULL,
    modified datetime NOT NULL,
    addon_id int(11) unsigned NOT NULL,
    region int(11) NOT NULL,
    UNIQUE (addon_id, region)
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE addons_excluded_regions ADD CONSTRAINT addons_excluded_regions_addon_id_fk
    FOREIGN KEY (addon_id) REFERENCES addons (id) ON DELETE CASCADE;

CREATE INDEX addons_excluded_regions_addon_id_idx ON addons_excluded_regions (addon_id);

CREATE INDEX addons_excluded_regions_region_idx ON addons_excluded_regions (region);
