CREATE TABLE `comm_threads` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` int(11) unsigned NOT NULL,
    `version_id` int(11) unsigned,
    `read_permission_public` bool NOT NULL,
    `read_permission_developer` bool NOT NULL,
    `read_permission_reviewer` bool NOT NULL,
    `read_permission_senior_reviewer` bool NOT NULL,
    `read_permission_mozilla_contact` bool NOT NULL,
    `read_permission_staff` bool NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `comm_threads` ADD CONSTRAINT `comm_threads_addon_id_key`
FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;

ALTER TABLE `comm_threads` ADD CONSTRAINT `comm_threads_version_id_key`
FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`) ON DELETE CASCADE;

CREATE TABLE `comm_thread_cc` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `thread_id` int(11) unsigned NOT NULL,
    `user_id` int(11) unsigned NOT NULL,
    UNIQUE (`user_id`, `thread_id`)
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `comm_thread_cc` ADD CONSTRAINT `thread_cc_thread_id_key`
FOREIGN KEY (`thread_id`) REFERENCES `comm_threads` (`id`) ON DELETE CASCADE;

ALTER TABLE `comm_thread_cc` ADD CONSTRAINT `thread_cc_user_id_key`
FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE;

CREATE TABLE `comm_thread_notes` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `thread_id` int(11) unsigned NOT NULL,
    `author_id` int(11) unsigned NOT NULL,
    `note_type` integer NOT NULL,
    `body` int(11) unsigned UNIQUE
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `comm_thread_notes` ADD CONSTRAINT `thread_notes_thread_id_key`
FOREIGN KEY (`thread_id`) REFERENCES `comm_threads` (`id`) ON DELETE CASCADE;

ALTER TABLE `comm_thread_notes` ADD CONSTRAINT `thread_notes_author_id_key`
FOREIGN KEY (`author_id`) REFERENCES `users` (`id`) ON DELETE CASCADE;

ALTER TABLE `comm_thread_notes` ADD CONSTRAINT `thread_notes_body_key`
FOREIGN KEY (`body`) REFERENCES `translations` (`id`) ON DELETE CASCADE;

CREATE TABLE `comm_thread_tokens` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `thread_id` int(11) unsigned NOT NULL,
    `user_id` int(11) unsigned NOT NULL,
    `uuid` char(32) NOT NULL UNIQUE,
    `use_count` integer NOT NULL,
    UNIQUE (`thread_id`, `user_id`)
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `comm_thread_tokens` ADD CONSTRAINT `thread_tokens_thread_id_key`
FOREIGN KEY (`thread_id`) REFERENCES `comm_threads` (`id`) ON DELETE CASCADE;

ALTER TABLE `comm_thread_tokens` ADD CONSTRAINT `thread_tokens_user_id_key`
FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE;

CREATE INDEX `comm_threads_269da59a` ON `comm_threads` (`addon_id`);
CREATE INDEX `comm_threads_fef0b09d` ON `comm_threads` (`version_id`);
CREATE INDEX `comm_thread_cc_9a6ed576` ON `comm_thread_cc` (`thread_id`);
CREATE INDEX `comm_thread_cc_fbfc09f1` ON `comm_thread_cc` (`user_id`);
CREATE INDEX `comm_thread_notes_9a6ed576` ON `comm_thread_notes` (`thread_id`);
CREATE INDEX `comm_thread_notes_cc846901` ON `comm_thread_notes` (`author_id`);
CREATE INDEX `comm_thread_tokens_fbfc09f1` ON `comm_thread_tokens` (`user_id`);
CREATE INDEX `comm_thread_tokens_9a6ed576` ON `comm_thread_tokens` (`thread_id`);
CREATE INDEX `comm_thread_tokens_uuid_index` ON `comm_thread_tokens` (`uuid`);
