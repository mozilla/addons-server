UPDATE translations_seq SET id=LAST_INSERT_ID(id + 1);
SELECT LAST_INSERT_ID() FROM translations_seq INTO @name;
insert into translations (id, locale, localized_string) VALUES
                         ((SELECT @name), 'en-US', 'All Platforms');

UPDATE translations_seq SET id=LAST_INSERT_ID(id + 1);
SELECT LAST_INSERT_ID() FROM translations_seq INTO @shortname;
INSERT INTO translations (id, locale, localized_string) VALUES
                         ((SELECT @shortname), 'en-US', 'allmobile');

INSERT INTO platforms (id, name, shortname) VALUES
                      (9, (SELECT @name), (SELECT @shortname));
