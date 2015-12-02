CREATE TABLE `email_preview` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `topic` varchar(255) NOT NULL,
    `recipient_list` longtext NOT NULL,
    `from_email` varchar(255) NOT NULL,
    `subject` varchar(255) NOT NULL,
    `body` longtext NOT NULL
)
;
CREATE INDEX `email_preview_277e394d` ON `email_preview` (`topic`);
