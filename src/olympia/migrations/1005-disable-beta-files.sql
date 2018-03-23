UPDATE files
SET status = 5
WHERE id IN
    (SELECT id
     FROM files
     WHERE status = 7);
