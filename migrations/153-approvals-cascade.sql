ALTER TABLE `approvals`
    DROP FOREIGN KEY `approvals_ibfk_3`;

ALTER TABLE `approvals` ADD CONSTRAINT `approvals_ibfk_3`
    FOREIGN KEY `approvals_ibfk_3` (`addon_id`)
    REFERENCES `addons` (`id`)
    ON DELETE CASCADE

