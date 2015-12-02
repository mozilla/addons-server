ALTER TABLE `approvals`
    DROP FOREIGN KEY `approvals_ibfk_2`;

ALTER TABLE `approvals` ADD CONSTRAINT `approvals_ibfk_2`
    FOREIGN KEY `approvals_ibfk_2` (`file_id`)
    REFERENCES `files` (`id`)
    ON DELETE CASCADE;

