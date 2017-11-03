ALTER TABLE `editors_autoapprovalsummary`
    DROP COLUMN `uses_custom_csp`,
    DROP COLUMN `uses_native_messaging`,
    DROP COLUMN `uses_content_script_for_all_urls`,
    DROP COLUMN `average_daily_users`,
    DROP COLUMN `approved_updates`,
    DROP COLUMN `has_info_request`,
    DROP COLUMN `is_under_admin_review`;
