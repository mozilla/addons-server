INSERT INTO `groups` (`name`, `rules`, `notes`, `created`, `modified`)
    VALUES ('Reviewers: Recommended', 'Addons:RecommendedReview', '', NOW(), NOW());
-- Also give this permission to the Staff group
UPDATE `groups` SET `rules` = CONCAT(`rules`, ',Addons:RecommendedReview') WHERE name = 'Staff';
