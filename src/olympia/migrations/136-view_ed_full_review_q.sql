-- bug 627502
CREATE OR REPLACE VIEW view_ed_full_review_q AS
    SELECT
        addons.id,
        tr.localized_string as addon_name,
        addons.status as addon_status,
        addons.addontype_id as addon_type_id,
        addons.adminreview as admin_review,
        addons.sitespecific as is_site_specific,
        GROUP_CONCAT(versions.id
                     ORDER BY versions.created DESC) as latest_version_ids,
        GROUP_CONCAT(versions.version
                     ORDER BY versions.created DESC SEPARATOR '&&&&') as
                                                        latest_versions,
        GROUP_CONCAT(DISTINCT files.platform_id) as file_platform_ids,
        TIMESTAMPDIFF(DAY,
                      addons.nominationdate, NOW()) as waiting_time_days,
        TIMESTAMPDIFF(HOUR,
                      addons.nominationdate, NOW()) as waiting_time_hours,
        GROUP_CONCAT(DISTINCT apps.application_id) as application_ids
    FROM files
    JOIN versions ON (files.version_id = versions.id)
    JOIN addons ON (versions.addon_id = addons.id)
    LEFT JOIN applications_versions as apps on versions.id = apps.version_id
    JOIN translations AS tr ON (tr.id = addons.name
                                AND tr.locale = addons.defaultlocale)
    WHERE
        -- 7=STATUS_BETA
        -- This helps to identify bugs in nomination process.
        -- TODO(Kumar) highlight the grid row when file is not
        -- STATUS_UNREVIEWED (see bug 627502).
        files.status <> 7
        -- STATUS_NOMINATED, STATUS_LITE_AND_NOMINATED
        AND addons.status IN (3, 9)
    GROUP BY id;
