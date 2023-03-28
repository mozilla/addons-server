SELECT `risk_category` AS `Risk Category`,
       IFNULL(FORMAT(SUM(n), 0), 0) AS `All Reviewers`,
       IFNULL(FORMAT(SUM(CASE WHEN `group_category` = 'volunteer' THEN n ELSE 0 END), 0), 0) AS 'Volunteers'
FROM
  (SELECT CASE
              WHEN `weight` > @RISK_HIGHEST THEN 'highest'
              WHEN `weight` > @RISK_HIGH THEN 'high'
              WHEN `weight` > @RISK_MEDIUM THEN 'medium'
              ELSE 'low'
          END AS `risk_category`,
          `group_category`,
          COUNT(*) AS `n`
   FROM `editors_autoapprovalsummary` `aa`
   JOIN
     (SELECT `version_id`,
             CASE WHEN `user_id` NOT IN
        (SELECT `user_id`
         FROM `groups_users`
         WHERE `group_id` IN
             (SELECT `id`
              FROM `groups`
              WHERE `name` = 'No Reviewer Incentives')) THEN 'volunteer' ELSE 'all' END AS `group_category`
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
      LEFT JOIN `versions` ON `versions`.`id` = `activity_ver`.`version_id`
      LEFT JOIN `addons` ON `addons`.`id` = `versions`.`addon_id`
      JOIN `users` `u` ON `u`.`id` = `activity`.`user_id`
      WHERE
        /* Filter out internal task user */
        `user_id` <> 4757633
        AND `u`.`deleted` = 0
        AND `addons`.`addontype_id` <> 10  /* We exclude theme reviews */
        AND (`activity_comment`.`comments` IS NULL OR `activity_comment`.`comments` != "Automatic rejection after grace period ended.")
     ) `reviews` ON `reviews`.`version_id` = `aa`.`version_id`
   GROUP BY `risk_category`,
            `group_category`) `risk`
GROUP BY 1
ORDER BY FIELD(`risk_category`,'highest','high','medium', 'low');
