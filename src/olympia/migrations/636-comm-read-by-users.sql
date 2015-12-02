CREATE TABLE `comm_notes_read` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `note_id` int(11) unsigned NOT NULL,
    `user_id` int(11) unsigned NOT NULL,
    UNIQUE (`note_id`, `user_id`)
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `comm_notes_read` ADD CONSTRAINT `userprofile_id_refs_id_4586e76` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
ALTER TABLE `comm_notes_read` ADD CONSTRAINT `communicationnote_id_refs_id_464e5d1` FOREIGN KEY (`note_id`) REFERENCES `comm_thread_notes` (`id`);

CREATE INDEX `comm_notes_read_note_index` ON `comm_notes_read` (`note_id`);
CREATE INDEX `comm_notes_read_user_index` ON `comm_notes_read` (`user_id`);
