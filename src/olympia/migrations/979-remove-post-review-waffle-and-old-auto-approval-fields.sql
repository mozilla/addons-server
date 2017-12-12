-- Old auto-approval fields that are no longer needed. We set them to nullable,
-- they'll be removed later to keep backwards-compatibility and not break
-- during push.
ALTER TABLE `editors_autoapprovalsummary`
    MODIFY `uses_custom_csp` tinyint(1) DEFAULT NULL,
    MODIFY `uses_native_messaging` tinyint(1) DEFAULT NULL,
    MODIFY `uses_content_script_for_all_urls` tinyint(1) DEFAULT NULL,
    MODIFY `average_daily_users` int(11) DEFAULT NULL,
    MODIFY `approved_updates` int(11) DEFAULT NULL,
    MODIFY `has_info_request` tinyint(1) DEFAULT NULL,
    MODIFY `is_under_admin_review` tinyint(1) DEFAULT NULL;

-- Remove post review waffle.
DELETE FROM waffle_switch WHERE name='post-review' LIMIT 1;
