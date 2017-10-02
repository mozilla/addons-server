ALTER TABLE `addons_addonapprovalscounter` ADD COLUMN `last_content_review` datetime(6) DEFAULT NULL;
UPDATE groups SET rules=CONCAT(rules, ',Addons:ContentReview') WHERE name IN ('Staff', 'Senior Add-on Reviewers');
