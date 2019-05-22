ALTER TABLE `users_user_email_restriction`
    DROP COLUMN `email`,
    ADD COLUMN `domain_pattern` varchar(100) NOT NULL;
