-- Move PENDING files to UNREVIEWED.
UPDATE files SET status=1 WHERE status=2;
