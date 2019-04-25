-- Disables old, unreviewed versions so they are no longer in the review
-- queues.  See bug 638307

-- This is a historic data fix.  The production fix was done for bug 630063 in
-- https://github.com/jbalogh/zamboni/commit/3a7d072

UPDATE files
    -- Change the file to STATUS_DISABLED if it was STATUS_UNREVIEWED
    SET status=5 WHERE status=1 AND EXISTS (
        SELECT v.id
        FROM versions v
        JOIN addons a on (a.id = v.addon_id)
        LEFT JOIN versions as newer_v on (newer_v.addon_id = a.id AND
                                          newer_v.created > v.created)
        WHERE
            v.id = files.version_id
            -- Make sure we are only updating *old* versions
            AND newer_v.id IS NOT NULL
            -- Make sure the file is for a preliminary or pending addon.
            -- (STATUS_APPROVED, STATUS_LITE, STATUS_UNREVIEWED,
            -- STATUS_DISABLED)
            AND a.status in (4, 8, 1, 5));
