DROP TABLE IF EXISTS `stats_contributions`, `charities`;

/* notification_id = 2 was the "thanks" contribution notification" */
DELETE FROM `users_notifications` WHERE `notification_id` = 2;
