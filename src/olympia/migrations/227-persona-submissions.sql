ALTER TABLE `personas` CHANGE COLUMN `approve` `approve` datetime NULL;

INSERT INTO `waffle_flag`
    (name, everyone, percent, superusers, staff, authenticated, rollout, note) VALUES
    ('submit-personas',0,NULL,1,0,0,0, 'Allow Personas to be submitted to AMO');
