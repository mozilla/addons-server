/*Addon author role constants:
 AUTHOR_ROLE_VIEWER = 1
 AUTHOR_ROLE_DEV = 4
 AUTHOR_ROLE_OWNER = 5
 AUTHOR_ROLE_SUPPORT = 6
*/

UPDATE `addons_users` SET `role`=4 WHERE `role` in (1,6);
