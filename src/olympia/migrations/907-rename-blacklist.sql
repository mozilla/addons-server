RENAME TABLE users_blacklistedname TO users_denied_name;
RENAME TABLE blacklisted_guids TO denied_guids;
RENAME TABLE addons_blacklistedslug TO addons_denied_slug;
ALTER TABLE tags CHANGE blacklisted denied tinyint(1) NOT NULL;
