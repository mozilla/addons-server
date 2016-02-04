INSERT INTO groups (name, rules, created, modified, notes)
    VALUES ('China Reviewers', 'Apps:ReviewRegionCN', NOW(), NOW(),
            'Reviewers in China are able to approve/reject apps in China.');

UPDATE groups SET rules=CONCAT(rules, ',Apps:ReviewRegionCN')
    WHERE name IN ('Staff', 'Senior App Reviewers');
