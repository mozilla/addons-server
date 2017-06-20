UPDATE groups SET rules=CONCAT(rules, ',Addons:PostReview') WHERE name IN ('Staff', 'Senior Add-on Reviewers');
