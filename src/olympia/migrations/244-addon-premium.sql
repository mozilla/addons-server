CREATE TABLE addons_premium (
    id int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    created datetime NOT NULL,
    modified datetime NOT NULL,
    addon_id int(11) unsigned NOT NULL UNIQUE,
    price_id int(11) NOT NULL,
    paypal_permissions_token varchar(255) NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE addons_premium ADD CONSTRAINT addon_id_refs_id_addons_premium FOREIGN KEY (addon_id) REFERENCES addons (id);
ALTER TABLE addons_premium ADD CONSTRAINT price_id_refs_id_addons_premium FOREIGN KEY (price_id) REFERENCES prices (id);
