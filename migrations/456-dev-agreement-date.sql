/* Doing this will mean the modify translates NULL to NULL. */
UPDATE `users` SET `read_dev_agreement` = NULL WHERE `read_dev_agreement` = 0;
ALTER TABLE `users` MODIFY `read_dev_agreement` DATETIME;
/* Flip everything that's not NULL to be the current timestamp. */
UPDATE `users` SET `read_dev_agreement` = current_timestamp
        WHERE `read_dev_agreement` is not NULL;
