SELECT IFNULL(`u`.`display_name`, CONCAT('Firefox user ', `u`.`id`)) AS `Name`,
       IF(
            (SELECT DISTINCT(`user_id`)
             FROM `groups_users`
             WHERE `group_id` IN
                 (SELECT `id`
                  FROM `groups`
                  WHERE `name` = 'No Reviewer Incentives')
               AND `user_id` = `activity`.`user_id`), '*', '') AS `Staff`,
       FORMAT(COUNT(*), 0) AS `Add-ons Reviewed`
FROM (
  SELECT `created`, `user_id`, `action`, MAX(`id`) AS `id`
  FROM `log_activity`
  WHERE DATE(`created`) BETWEEN @WEEK_BEGIN AND @WEEK_END
  /* The type of review, see constants/activity.py */
  AND `action` IN (147, 148, 164)
  GROUP BY `created`, `user_id`, `action`
) AS `activity`
LEFT JOIN `log_activity_comment` `activity_comment` ON `activity_comment`.`activity_log_id` = `activity`.`id`
JOIN `users` `u` ON `u`.`id` = `activity`.`user_id`
WHERE
  /* Filter out internal task user */
  `user_id` <> 4757633
  AND `u`.`deleted` = 0
  AND (`activity_comment`.`comments` IS NULL OR `activity_comment`.`comments` != "Automatic rejection after grace period ended.")
GROUP BY `user_id` HAVING `Add-ons Reviewed` >= 10
ORDER BY `Add-ons Reviewed` DESC;
