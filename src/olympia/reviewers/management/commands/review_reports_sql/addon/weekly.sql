SELECT IFNULL(`u`.`display_name`, CONCAT('Firefox user ', `u`.`id`)) AS `Name`,
       IF(
            (SELECT DISTINCT(`user_id`)
             FROM `groups_users`
             WHERE `group_id` IN
                 (SELECT `id`
                  FROM `groups`
                  WHERE `name` = 'No Reviewer Incentives')
               AND `user_id` = `activity`.`user_id`), '*', '') AS `Staff`,
       IFNULL(FORMAT(SUM(`aa`.`weight`), 0), 0) AS `Total Risk`,
       IFNULL(FORMAT(AVG(`aa`.`weight`), 2), 0) AS `Average Risk`,
       FORMAT(COUNT(*), 0) AS `Add-ons Reviewed`
FROM (
  /* NOTE: This works to reduce reviews that acted on multiple reviews to a single review
     because we set created to be the exact same datetime. */
  SELECT `created`, `user_id`, `action`, MAX(`id`) AS `id`
  FROM `log_activity`
  WHERE DATE(`created`) BETWEEN @WEEK_BEGIN AND @WEEK_END
  /* The type of review, see constants/activity.py */
  AND FIND_IN_SET(`action`, @ACTIVITY_ID_LIST) > 0
  GROUP BY `created`, `user_id`, `action`
) AS `activity`
JOIN `log_activity_version` `activity_ver` ON `activity_ver`.`activity_log_id` = `activity`.`id`
LEFT JOIN `log_activity_comment` `activity_comment` ON `activity_comment`.`activity_log_id` = `activity`.`id`
LEFT JOIN `editors_autoapprovalsummary` `aa` ON `aa`.`version_id` = `activity_ver`.`version_id`
JOIN `users` `u` ON `u`.`id` = `activity`.`user_id`
WHERE
  /* Filter out internal task user */
  `user_id` <> 4757633
  AND `u`.`deleted` = 0
  AND (`activity_comment`.`comments` IS NULL OR `activity_comment`.`comments` != "Automatic rejection after grace period ended.")
GROUP BY `user_id` HAVING `Add-ons Reviewed` >= 5
ORDER BY SUM(`aa`.`weight`) DESC;
