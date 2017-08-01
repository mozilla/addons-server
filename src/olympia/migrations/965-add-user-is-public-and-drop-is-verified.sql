ALTER TABLE users
    ADD COLUMN `public` boolean DEFAULT false,
    DROP COLUMN `is_verified`;

/* AUTHOR_ROLE_DEV = 4
AUTHOR_ROLE_OWNER = 5
STATUS_PUBLIC = 4 */

UPDATE users, addons_users, addons SET users.`public`=true
    WHERE users.`id`=addons_users.`user_id` and
          addons_users.`role` in (4, 5) and
          addons_users.`listed`=true and
          addons_users.`addon_id`=addons.`id` and
          addons.`status`=4;
