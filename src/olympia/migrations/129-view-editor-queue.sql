-- bug 622172
CREATE OR REPLACE VIEW view_editor_queue AS
    SELECT
        addons.id,
        versions.id as version_id,
        CONCAT_WS(' ', tr.localized_string,
                  versions.version) as addon_name,
        addons.addontype_id as addon_type_id,
        addons.adminreview as admin_review,
        addons.sitespecific as is_site_specific,
        files.platform_id,
        versions.created as version_created,
        addons.nominationdate as nomination_date,
        TIMESTAMPDIFF(DAY, versions.created,
                      NOW()) as days_since_created,
        TIMESTAMPDIFF(HOUR, versions.created,
                      NOW()) as hours_since_created,
        TIMESTAMPDIFF(DAY, addons.nominationdate,
                      NOW()) as days_since_nominated,
        TIMESTAMPDIFF(HOUR, addons.nominationdate,
                      NOW()) as hours_since_nominated,
        GROUP_CONCAT(apps.application_id) as applications
        -- ,
        -- GROUP_CONCAT(vs.application_id) as version_apps,
        -- GROUP_CONCAT(app_versions_min.version) as version_min,
        -- GROUP_CONCAT(app_versions_max.version) as version_max
    FROM files
    JOIN versions ON (files.version_id = versions.id)
    JOIN addons ON (versions.addon_id = addons.id)
    JOIN applications_versions as apps on versions.id = apps.version_id
    JOIN translations AS tr ON (tr.id = addons.name
                                AND tr.locale = addons.defaultlocale)
    -- JOIN versions_summary as vs ON
    --             (versions.id = vs.version_id
    --              AND vs.application_id = apps.application_id)
    -- JOIN versions as app_versions_min ON app_versions_min.id = vs.min
    -- JOIN versions as app_versions_max ON app_versions_min.id = vs.max
    -- STATUS_SANDBOX in remora, STATUS_UNREVIEWED in zamboni
    WHERE files.status=1
    -- STATUS_APPROVED
    AND addons.status=4
    GROUP BY 1, 2;
