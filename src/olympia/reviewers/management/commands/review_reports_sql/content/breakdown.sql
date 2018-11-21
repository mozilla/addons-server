SELECT 'All Reviewers' AS `Group`,
       FORMAT(COUNT(*), 0) AS `Add-ons Reviewed`
FROM editors_autoapprovalsummary aa
JOIN reviewer_scores rs ON rs.version_id = aa.version_id
WHERE DATE(rs.created) BETWEEN @WEEK_BEGIN AND @WEEK_END
  AND user_id <> 4757633
  AND rs.note_key IN (101)
UNION ALL
SELECT 'Volunteers' AS `Group`,
       FORMAT(COUNT(*), 0) AS `Add-ons Reviewed`
FROM editors_autoapprovalsummary aa
JOIN reviewer_scores rs ON rs.version_id = aa.version_id
WHERE DATE(rs.created) BETWEEN @WEEK_BEGIN AND @WEEK_END
  AND user_id <> 4757633
  AND rs.note_key IN (101)
  AND rs.user_id NOT IN
    (SELECT user_id
     FROM groups_users
     WHERE group_id IN
         (SELECT id
          FROM groups
          WHERE name IN ('Staff', 'No Reviewer Incentives')));
