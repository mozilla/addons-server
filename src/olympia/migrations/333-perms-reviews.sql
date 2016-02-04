ALTER TABLE `groups` ADD COLUMN `notes` longtext NOT NULL;

UPDATE groups SET rules=CONCAT(rules, ",Reviews:Edit")
    WHERE id IN (50002, 50003, 50004, 50005);
