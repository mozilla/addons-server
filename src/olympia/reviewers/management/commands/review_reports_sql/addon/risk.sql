SELECT risk_category AS `Risk Category`,
       FORMAT(SUM(n), 0) AS `All Reviewers`,
       FORMAT(SUM(CASE WHEN `gruppe` = 'volunteer' THEN n ELSE 0 END), 0) AS 'Volunteers'
FROM (
    SELECT CASE
               WHEN weight > @RISK_HIGHEST THEN 'highest'
               WHEN weight > @RISK_HIGH THEN 'high'
               WHEN weight > @RISK_MEDIUM THEN 'medium'
               ELSE 'low'
           END AS risk_category,
           gruppe,
           COUNT(*) as n
 FROM editors_autoapprovalsummary aa
   JOIN
     (SELECT version_id,
             CASE WHEN user_id NOT IN
        (SELECT user_id
         FROM groups_users
         WHERE group_id IN (
           SELECT id FROM groups WHERE name IN ('Staff', 'No Reviewer Incentives')
         )) THEN 'volunteer' ELSE 'all' END AS `gruppe`
      FROM reviewer_scores rs
      WHERE DATE(rs.created) BETWEEN @WEEK_BEGIN AND @WEEK_END
        AND user_id <> 4757633
        AND rs.note_key IN (10, 12, 20, 22, 30, 32, 50, 52, 102, 103, 104, 105)) iner on iner.version_id = aa.version_id
   GROUP BY risk_category, `gruppe`
   ) tmp
GROUP BY 1
ORDER BY FIELD(risk_category,'highest','high','medium', 'low');
