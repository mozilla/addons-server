SELECT IFNULL(u.display_name, CONCAT('Firefox user ', u.id)) AS `Name`,
       IFNULL(FORMAT(SUM(rs.score), 0), 0) AS `Points`,
       FORMAT(COUNT(*), 0) AS `Add-ons Reviewed`
FROM reviewer_scores rs
JOIN users u ON u.id = rs.user_id
WHERE DATE(rs.created) BETWEEN @QUARTER_BEGIN AND @WEEK_END
  AND u.deleted = 0
  /* Filter out internal task user */
  AND user_id <> 4757633
  /* The type of review, see constants/reviewers.py */
  AND rs.note_key IN (10, 12, 20, 22, 30, 32, 50, 52, 102, 103, 104, 105)
  AND rs.user_id NOT IN
    (SELECT user_id
     FROM groups_users
     WHERE group_id IN
         (SELECT id
          FROM groups
          WHERE name = 'No Reviewer Incentives'))
GROUP BY rs.user_id
ORDER BY SUM(rs.score) DESC;
