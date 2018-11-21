SELECT u.display_name AS `Name`,
       IFNULL(FORMAT(SUM(rs.score), 0), 0) AS `Points`,
       FORMAT(COUNT(*), 0) AS `Add-ons Reviewed`
FROM reviewer_scores rs
JOIN users u ON u.id = rs.user_id
WHERE DATE(rs.created) BETWEEN @QUARTER_BEGIN AND @WEEK_END
  AND user_id <> 4757633
  AND rs.note_key IN (101)
  AND rs.user_id NOT IN
    (SELECT user_id
     FROM groups_users
     WHERE group_id IN
         (SELECT id
          FROM groups
          WHERE name IN ('Staff', 'No Reviewer Incentives')))
GROUP BY rs.user_id
ORDER BY SUM(rs.score) DESC;
