-- bug 622172
CREATE OR REPLACE VIEW view_ed_pending_q AS
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
                      MAX(versions.created), NOW()) as waiting_time_days,
        TIMESTAMPDIFF(HOUR,
                      MAX(versions.created), NOW()) as waiting_time_hours,
        GROUP_CONCAT(DISTINCT apps.application_id) as application_ids
    FROM files
    JOIN versions ON (files.version_id = versions.id)
    JOIN addons ON (versions.addon_id = addons.id)
    JOIN applications_versions as apps on versions.id = apps.version_id
    JOIN translations AS tr ON (tr.id = addons.name
                                AND tr.locale = addons.defaultlocale)
    WHERE
        -- STATUS_UNREVIEWED
        files.status = 1
        -- STATUS_APPROVED
        AND addons.status = 4
    GROUP BY id;
