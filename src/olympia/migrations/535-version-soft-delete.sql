ALTER TABLE versions
    ADD COLUMN deleted tinyint(1) UNSIGNED NOT NULL DEFAULT '0';
