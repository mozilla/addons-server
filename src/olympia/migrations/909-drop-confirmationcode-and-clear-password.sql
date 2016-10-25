ALTER TABLE users
    DROP COLUMN `confirmationcode`;

UPDATE users SET password='';
