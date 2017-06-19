INSERT INTO waffle_switch (name, active, note, created, modified)
VALUES ('post-review', 0, 'When post-review is enabled, all webextensions are automatically approved periodically by auto_approve command and reviewed by humans a posteriori.', NOW(), NOW());
