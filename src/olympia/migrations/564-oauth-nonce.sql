ALTER TABLE `api_access` ADD COLUMN `redirect_uri` varchar(255) default NULL;
ALTER TABLE `api_access` ADD COLUMN `app_name` varchar(255) default NULL;

CREATE TABLE `oauth_nonce` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `nonce` varchar(128) NOT NULL,
    `timestamp` integer NOT NULL,
    `client_key` varchar(255) NOT NULL,
    `request_token` varchar(128),
    `access_token` varchar(128),
    UNIQUE (`nonce`, `timestamp`, `client_key`, `request_token`, `access_token`)
    ) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

CREATE TABLE `oauth_token` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `token_type` integer NOT NULL,
    `creds_id` int(11) unsigned NOT NULL,
    `key` varchar(255) NOT NULL,
    `secret` varchar(255) NOT NULL,
    `timestamp` integer NOT NULL,
    `user_id` int(11),
    `verifier` varchar(255)
    ) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `oauth_token` ADD CONSTRAINT `creds_id_refs_id_3bd47889` FOREIGN KEY (`creds_id`) REFERENCES `api_access` (`id`);
ALTER TABLE `oauth_token` ADD CONSTRAINT `user_id_refs_id_e213c7fc` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`);
