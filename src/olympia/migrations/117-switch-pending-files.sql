-- Disable UNREVIEWED files on PUBLIC add-ons.
UPDATE (files f INNER JOIN versions v ON f.version_id=v.id
        INNER JOIN addons a ON a.id=v.addon_id)
  SET f.status=5 WHERE f.status=1 AND a.status=4;

-- Move PENDING files to UNREVIEWED.
UPDATE files SET status=1 WHERE status=2;
