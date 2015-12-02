ALTER TABLE addons
    ADD COLUMN current_version int(11) UNSIGNED,
    ADD CONSTRAINT
        FOREIGN KEY (current_version)
            REFERENCES versions (id) ON DELETE SET NULL;
