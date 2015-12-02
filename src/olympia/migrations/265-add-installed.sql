CREATE TABLE users_install (
    id int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    created datetime NOT NULL,
    modified datetime NOT NULL,
    addon_id int(11) unsigned NOT NULL,
    user_id int(11) unsigned NOT NULL,
    UNIQUE (addon_id, user_id)
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE users_install ADD CONSTRAINT addon_id_refs_id FOREIGN KEY (addon_id) REFERENCES addons (id);
ALTER TABLE users_install ADD CONSTRAINT user_id_refs_id FOREIGN KEY (user_id) REFERENCES users (id);
CREATE INDEX users_install_addon_idx ON users_install (addon_id);
CREATE INDEX users_install_user_idx ON users_install (user_id);
