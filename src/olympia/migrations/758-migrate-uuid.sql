ALTER TABLE addon_purchase ADD COLUMN `uuid` varchar(255) NULL UNIQUE;

UPDATE addon_purchase INNER JOIN users_install
    ON (addon_purchase.user_id = users_install.user_id
        AND addon_purchase.addon_id = users_install.addon_id)
    SET addon_purchase.uuid = users_install.uuid;

ALTER TABLE addon_purchase CHANGE `uuid` `uuid` varchar(255) NOT NULL UNIQUE;
