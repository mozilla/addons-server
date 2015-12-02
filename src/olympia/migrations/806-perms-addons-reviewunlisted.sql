UPDATE groups
SET rules=CONCAT(rules, ',Addons:ReviewUnlisted')
WHERE groups.name='Senior Add-on Reviewers';
