-- Note: if the migration fails for you locally, remove the 'unsigned' next to addon_id below.
CREATE TABLE `addons_addonapprovalscounter` (
    `created` datetime(6) NOT NULL,
    `modified` datetime(6) NOT NULL,
    `addon_id` integer UNSIGNED NOT NULL PRIMARY KEY,
    `counter` integer UNSIGNED NOT NULL
);
ALTER TABLE `addons_addonapprovalscounter` ADD CONSTRAINT `addon_id_refs_id_8fcb7166` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);

-- Start all existing public addons at 1: they had to have at least one human review to be public.
INSERT INTO addons_addonapprovalscounter (addon_id, counter, created, modified) SELECT id, 1, NOW(), NOW() FROM addons WHERE status = 4 AND inactive = false;
