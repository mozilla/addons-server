ALTER TABLE app_collections MODIFY COLUMN default_language varchar(10) not null default 'en-US';
UPDATE app_collections SET default_language = 'en-US' WHERE default_language = 'en-us';
