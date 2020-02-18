SELECT risk_category AS `Risk Category`,
       IFNULL(FORMAT(SUM(n), 0), 0) AS `All Reviewers`,
       IFNULL(FORMAT(SUM(CASE WHEN `group_category` = 'volunteer' THEN n ELSE 0 END), 0), 0) AS 'Volunteers'
FROM
  (SELECT CASE
              WHEN weight > @RISK_HIGHEST THEN 'highest'
              WHEN weight > @RISK_HIGH THEN 'high'
              WHEN weight > @RISK_MEDIUM THEN 'medium'
              ELSE 'low'
          END AS risk_category,
          group_category,
          COUNT(*) AS n
   FROM editors_autoapprovalsummary aa
   JOIN
     (SELECT version_id,
             CASE WHEN user_id NOT IN
        (SELECT user_id
         FROM groups_users
         WHERE group_id IN
             (SELECT id
              FROM groups
              WHERE name = 'No Reviewer Incentives')) THEN 'volunteer' ELSE 'all' END AS `group_category`
      FROM reviewer_scores rs
      JOIN users u ON u.id = rs.user_id
      WHERE DATE(rs.created) BETWEEN @WEEK_BEGIN AND @WEEK_END
        AND u.deleted = 0
        /* Filter out internal task user */
        AND user_id <> 4757633
        /* The type of review, see constants/reviewers.py */
        AND rs.note_key IN (10, 12, 20, 22, 30, 32, 50, 52, 102, 103, 104, 105)) reviews ON reviews.version_id = aa.version_id
   GROUP BY risk_category,
            `group_category`) risk
GROUP BY 1
ORDER BY FIELD(risk_category,'highest','high','medium', 'low');
