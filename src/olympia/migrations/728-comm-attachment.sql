CREATE TABLE `comm_attachments` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `note_id` int(11) unsigned NOT NULL,
    `filepath` varchar(255) NOT NULL,
    `description` varchar(255),
    `mimetype` varchar(255)
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;
 ALTER TABLE `comm_attachments`
    ADD CONSTRAINT `comm_attachment_comm_thread_note_fk`
    FOREIGN KEY (`note_id`) REFERENCES `comm_thread_notes` (`id`)
    ON DELETE CASCADE;
