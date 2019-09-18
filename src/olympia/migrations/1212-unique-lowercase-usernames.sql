/* Create a table with all usernames that have duplicates in lowercase. */
CREATE TABLE `duplicate_usernames`
    SELECT LOWER(`username`) AS `username` FROM `users`
        GROUP BY LOWER(`username`) HAVING COUNT(*) > 1;
/* Update the username for all users in that table that have a username and lowercase username not being equal. */
UPDATE `users`
    SET `username`=CONCAT('anonymous-', LEFT(MD5(RAND()), 32))
    WHERE LOWER(`username`) != `username`
    AND LOWER(`username`) IN (SELECT `username` FROM `duplicate_usernames`);
/* Alter users, removing the utf8mb4_bin collation now that duplicates should be gone. */
ALTER TABLE `users` CHANGE COLUMN `username` `username` VARCHAR (255) NOT NULL;
