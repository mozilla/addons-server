UPDATE
    `users`
SET
    `username` = CONCAT(SUBSTR(`username`, 1, 145),
                        '-2-7182818')
WHERE
    `username` RLIKE '^[0-9]+$';
