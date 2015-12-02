-- file_validation was always one to one in practice
-- but this should add extra sanity since the django
-- model is now officially 1:1

ALTER TABLE file_validation ADD UNIQUE (file_id);