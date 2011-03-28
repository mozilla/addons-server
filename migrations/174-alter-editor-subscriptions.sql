ALTER TABLE editor_subscriptions ADD COLUMN created datetime NOT NULL;
ALTER TABLE editor_subscriptions ADD COLUMN modified datetime NOT NULL;
ALTER TABLE editor_subscriptions DROP PRIMARY KEY;
ALTER TABLE editor_subscriptions ADD COLUMN id integer AUTO_INCREMENT NOT NULL PRIMARY KEY;
