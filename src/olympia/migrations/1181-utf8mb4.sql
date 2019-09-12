ALTER TABLE `editor_subscriptions` COMMENT '';

ALTER TABLE `addons_reusedguid` CONVERT TO CHARACTER SET utf8mb4;
ALTER TABLE `addons_users_pending_confirmation` CONVERT TO CHARACTER SET utf8mb4;
ALTER TABLE `api_apikeyconfirmation` CONVERT TO CHARACTER SET utf8mb4;
ALTER TABLE `hero_primaryhero` CONVERT TO CHARACTER SET utf8mb4;
ALTER TABLE `hero_secondaryhero` CONVERT TO CHARACTER SET utf8mb4;
ALTER TABLE `hero_secondaryheromodule` CONVERT TO CHARACTER SET utf8mb4;
ALTER TABLE `log_activity_comment_draft` CONVERT TO CHARACTER SET utf8mb4;
ALTER TABLE `scanners_results` CONVERT TO CHARACTER SET utf8mb4;
ALTER TABLE `users_disposable_email_domain_restriction` CONVERT TO CHARACTER SET utf8mb4;
ALTER TABLE `users_user_email_restriction` CONVERT TO CHARACTER SET utf8mb4;
ALTER TABLE `users_user_network_restriction` CONVERT TO CHARACTER SET utf8mb4;
ALTER TABLE `users_userrestrictionhistory` CONVERT TO CHARACTER SET utf8mb4;
ALTER TABLE `yara_results` CONVERT TO CHARACTER SET utf8mb4;
