-- As documented in bug 647769 there are versions with null
-- nomination dates.  These were fixed in migration 181.
-- For some reason there are also orphaned versions that
-- do not have a valid nominated version.  This fixes those by
-- setting their nomination date equal to version creation date.
UPDATE addons a
    JOIN versions v on v.addon_id=a.id
    LEFT JOIN versions good_v on (good_v.addon_id=a.id
                                  and good_v.nomination is not null)
    JOIN files f on f.version_id=v.id
    SET v.nomination = v.created
    -- STATUS_NOMINATED, STATUS_LITE_AND_NOMINATED
    WHERE a.status in (3,9)
    AND v.nomination is NULL
    -- this only fixes the orphans (those without a previously
    -- nominated version)
    AND good_v.id is null
    -- STATUS_BETA
    AND f.status <> 7;
