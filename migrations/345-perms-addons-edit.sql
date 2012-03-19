UPDATE groups
SET rules=CONCAT(rules, ',Addons:Edit')
WHERE groups.name='Senior Add-on Reviewers' AND id >= 50000;
