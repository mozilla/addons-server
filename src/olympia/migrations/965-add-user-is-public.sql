ALTER TABLE users
    ADD COLUMN `public` boolean DEFAULT FALSE;

/* AUTHOR_ROLE_DEV = 4
AUTHOR_ROLE_OWNER = 5
STATUS_PUBLIC = 4 */

UPDATE users, addons_users, addons SET users.`public` = TRUE
    WHERE users.`id` = addons_users.`user_id` AND
          addons_users.`role` IN (4, 5) AND
          addons_users.`listed` = TRUE AND
          addons_users.`addon_id` = addons.`id` AND
          addons.`status` = 4;
