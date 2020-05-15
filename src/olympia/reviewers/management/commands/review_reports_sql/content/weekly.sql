SELECT IFNULL(u.display_name, CONCAT('Firefox user ', u.id)) AS `Name`,
       IF(
            (SELECT DISTINCT(user_id)
             FROM groups_users
             WHERE group_id IN
                 (SELECT id
                  FROM groups
                  WHERE name = 'No Reviewer Incentives')
               AND user_id = rs.user_id), '*', '') AS `Staff`,
       IFNULL(IF(
                   (SELECT DISTINCT(user_id)
                    FROM groups_users
                    WHERE group_id IN
                        (SELECT id
                         FROM groups
                         WHERE name = 'No Reviewer Incentives')
                      AND user_id = rs.user_id), '-', SUM(rs.score)), 0) AS `Points`,
       FORMAT(COUNT(*), 0) AS `Add-ons Reviewed`
FROM reviewer_scores rs
LEFT JOIN editors_autoapprovalsummary aa ON aa.version_id = rs.version_id
JOIN users u ON u.id = rs.user_id
WHERE DATE(rs.created) BETWEEN @WEEK_BEGIN AND @WEEK_END
  AND u.deleted = 0
  /* Filter out internal task user */
  AND user_id <> 4757633
  /* The type of review, see constants/reviewers.py */
  AND rs.note_key IN (101)
GROUP BY user_id HAVING `Add-ons Reviewed` >= 10
ORDER BY `Add-ons Reviewed` DESC;
