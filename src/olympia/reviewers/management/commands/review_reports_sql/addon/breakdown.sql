SELECT 'All Reviewers' AS `Group`,
       IFNULL(FORMAT(SUM(aa.weight), 0), '-') AS `Total Risk`,
       IFNULL(FORMAT(AVG(aa.weight), 2), '-') AS `Average Risk`,
       FORMAT(COUNT(*), 0) AS `Add-ons Reviewed`
FROM editors_autoapprovalsummary aa
JOIN reviewer_scores rs ON rs.version_id = aa.version_id
WHERE DATE(rs.created) BETWEEN @WEEK_BEGIN AND @WEEK_END
 /* Filter out internal task user */
  AND user_id <> 4757633
  /* The type of review, see constants/reviewers.py */
  AND rs.note_key IN (10, 12, 20, 22, 30, 32, 50, 52, 102, 103, 104, 105)
UNION ALL
SELECT 'Volunteers' AS `Group`,
       IFNULL(FORMAT(SUM(aa.weight), 0), '-') AS `Total Risk`,
       IFNULL(FORMAT(AVG(aa.weight), 2), '-') AS `Average Risk`,
       FORMAT(COUNT(*), 0) AS `Add-ons Reviewed`
FROM editors_autoapprovalsummary aa
JOIN reviewer_scores rs ON rs.version_id = aa.version_id
WHERE DATE(rs.created) BETWEEN @WEEK_BEGIN AND @WEEK_END
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
          WHERE name IN ('Staff', 'No Reviewer Incentives')));
