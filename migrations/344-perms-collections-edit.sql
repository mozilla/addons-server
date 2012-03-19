UPDATE groups
SET rules=CONCAT(rules, ',Collections:Edit')
WHERE groups.name='Senior Add-on Reviewers' AND id >= 50000;
