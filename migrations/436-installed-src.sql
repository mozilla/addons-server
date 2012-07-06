ALTER TABLE users_install ADD COLUMN source VARCHAR(255) NULL;
ALTER TABLE users_install ADD COLUMN device_type VARCHAR(255) NULL;
ALTER TABLE users_install ADD COLUMN user_agent VARCHAR(255) NULL;
ALTER TABLE users_install ADD COLUMN is_chromeless bool;
ALTER TABLE stats_contributions ADD COLUMN device_type VARCHAR(255) NULL;
ALTER TABLE stats_contributions ADD COLUMN user_agent VARCHAR(255) NULL;
ALTER TABLE stats_contributions ADD COLUMN is_chromeless bool;
