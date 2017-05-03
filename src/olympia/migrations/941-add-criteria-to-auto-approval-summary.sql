ALTER TABLE `editors_autoapprovalsummary`
    ADD COLUMN `has_info_request` bool NOT NULL,
    ADD COLUMN `is_locked` bool NOT NULL,
    ADD COLUMN `is_under_admin_review` bool NOT NULL;
