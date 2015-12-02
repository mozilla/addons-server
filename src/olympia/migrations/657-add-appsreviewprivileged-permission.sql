UPDATE groups SET rules=CONCAT(rules, ',Apps:ReviewPrivileged') WHERE name IN ('Staff', 'Senior App Reviewers');
