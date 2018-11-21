SELECT u.display_name AS `Name`,
       IF(
            (SELECT DISTINCT(user_id)
             FROM groups_users
             WHERE group_id IN
                 (SELECT id
                  FROM groups
                  WHERE name IN ('Staff', 'No Reviewer Incentives'))
               AND user_id = rs.user_id), '*', '') AS `Staff`,
       FORMAT(SUM(aa.weight), 0) AS `Total Risk`,
       FORMAT(AVG(aa.weight), 2) AS `Average Risk`,
       IFNULL(IF(
                   (SELECT DISTINCT(user_id)
                    FROM groups_users
                    WHERE group_id IN
                        (SELECT id
                         FROM groups
                         WHERE name IN ('Staff', 'No Reviewer Incentives'))
                      AND user_id = rs.user_id), '-', SUM(rs.score)), 0) AS `Points`,
       FORMAT(COUNT(*), 0) AS `Add-ons Reviewed`
FROM editors_autoapprovalsummary aa
JOIN reviewer_scores rs ON rs.version_id = aa.version_id
JOIN users u ON u.id = rs.user_id
WHERE DATE(rs.created) BETWEEN @WEEK_BEGIN AND @WEEK_END
  AND user_id <> 4757633
  AND rs.note_key IN (10, 12, 20, 22, 30, 32, 50, 52, 102, 103, 104, 105)
GROUP BY user_id HAVING `Add-ons Reviewed` >= 5
ORDER BY SUM(aa.weight) DESC;
