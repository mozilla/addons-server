-- We added a unique key on the id field in translations/models.py to fake out
-- Django.  Django's syncdb tries to build the database in these steps:
--   1. Create tables.
--   2. Create foreign key constraints between tables.
--   3. Create indexes.
--
-- But! translations are goofy and we create foreign keys to `id`, which does
-- not actually have a key constraint.  You can't create foreign keys without
-- key constraints using InnoDB, and we can't rely on Django to create an index
-- since that happens after foreign keys.  Thus, we use a fake unique key during
-- table creation so that foreign keys can be resolved.  This was our first
-- great zamboni hack. -- jbalogh and davedash

ALTER TABLE translations
    DROP KEY `id`;
