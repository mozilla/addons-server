INSERT INTO api_access (`key`, `secret`, `user_id`, `created`, `modified`)
SELECT `key`, `secret`, `user_id`, NOW(), NOW()
FROM piston_consumer WHERE user_id IS NOT NULL;
