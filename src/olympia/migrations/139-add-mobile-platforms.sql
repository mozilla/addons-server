UPDATE translations_seq SET id=LAST_INSERT_ID(id + 1);
SELECT LAST_INSERT_ID() FROM translations_seq INTO @id;
insert into translations (id, locale, localized_string) VALUES
                         ((SELECT @id), 'en-US', 'Android');
INSERT INTO platforms (id, name) VALUES (7, (SELECT @id));

UPDATE translations_seq SET id=LAST_INSERT_ID(id + 1);
SELECT LAST_INSERT_ID() FROM translations_seq INTO @id;
INSERT INTO translations (id, locale, localized_string) VALUES
                         ((SELECT @id), 'en-US', 'android');
UPDATE platforms SET shortname = @id WHERE id=7;

UPDATE translations_seq SET id=LAST_INSERT_ID(id + 1);
SELECT LAST_INSERT_ID() FROM translations_seq INTO @id;
INSERT INTO translations (id, locale, localized_string) VALUES
                         ((SELECT @id), 'en-US', 'Maemo');
INSERT INTO platforms (id, name) VALUES (8, (SELECT @id));

UPDATE translations_seq SET id=LAST_INSERT_ID(id + 1);
SELECT LAST_INSERT_ID() FROM translations_seq INTO @id;
INSERT INTO translations (id, locale, localized_string) VALUES
                         ((SELECT @id), 'en-US', 'maemo');
UPDATE platforms SET shortname = @id WHERE id=8;
