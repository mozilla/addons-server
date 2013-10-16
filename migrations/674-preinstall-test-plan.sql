CREATE TABLE `preinstall_test_plan` (
    `id` int(11) unsigned NOT NULL auto_increment,
    `addon_id` int(11) unsigned NOT NULL,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `last_submission` datetime NOT NULL,
    `filename` char(60) NOT NULL,
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

ALTER TABLE `preinstall_test_plan` ADD CONSTRAINT `preinstall_test_plan_addon_fk` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);

INSERT INTO waffle_switch_mkt (name, active, created, modified, note)
VALUES ('preinstall-apps', 0, NOW(), NOW(), 'Submission process for preinstalled apps.');
