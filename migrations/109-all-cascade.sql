SET FOREIGN_KEY_CHECKS=0;

-- ALTER TABLE `addons_collections` DROP FOREIGN KEY `addons_collections_ibfk_3`;

ALTER TABLE `addons_collections`
    ADD CONSTRAINT `addons_collections_ibfk_3`
        FOREIGN KEY `addons_collections_ibfk_3` (`user_id`)
        REFERENCES `users` (`id`)
        ON DELETE CASCADE;

ALTER TABLE `api_auth_tokens` DROP FOREIGN KEY `api_auth_tokens_ibfk_1`;

ALTER TABLE `api_auth_tokens`
    ADD CONSTRAINT `api_auth_tokens_ibfk_1`
        FOREIGN KEY `api_auth_tokens_ibfk_1` (`user_id`)
        REFERENCES `users` (`id`)
        ON DELETE CASCADE;

ALTER TABLE `collection_subscriptions`
    DROP FOREIGN KEY `collections_subscriptions_ibfk_2`;

ALTER TABLE `collection_subscriptions`
    ADD CONSTRAINT `collections_subscriptions_ibfk_2`
        FOREIGN KEY `collections_subscriptions_ibfk_2` (`user_id`)
        REFERENCES `users` (`id`)
        ON DELETE CASCADE;

ALTER TABLE `collections_users` DROP FOREIGN KEY `collections_users_ibfk_2`;

ALTER TABLE `collections_users`
    ADD CONSTRAINT `collections_users_ibfk_2`
        FOREIGN KEY `collections_users_ibfk_2` (`user_id`)
        REFERENCES `users` (`id`)
        ON DELETE CASCADE;

ALTER TABLE `collections_votes` DROP FOREIGN KEY `collections_votes_ibfk_2`;

ALTER TABLE `collections_votes`
    ADD CONSTRAINT `collections_votes_ibfk_2`
        FOREIGN KEY `collections_votes_ibfk_2` (`user_id`)
        REFERENCES `users` (`id`)
        ON DELETE CASCADE;

ALTER TABLE `reviewratings` DROP FOREIGN KEY `reviewratings_ibfk_2`;

ALTER TABLE `reviewratings`
    ADD CONSTRAINT `reviewratings_ibfk_2`
        FOREIGN KEY `reviewratings_ibfk_2` (`user_id`)
        REFERENCES `users` (`id`)
        ON DELETE CASCADE;

ALTER TABLE `versioncomments` DROP FOREIGN KEY `versioncomments_ibfk_2`;

ALTER TABLE `versioncomments`
    ADD CONSTRAINT `versioncomments_ibfk_2`
        FOREIGN KEY `versioncomments_ibfk_2` (`user_id`)
        REFERENCES `users` (`id`)
        ON DELETE CASCADE;

ALTER TABLE `reviews_moderation_flags`
    DROP FOREIGN KEY `reviews_moderation_flags_ibfk_2`;

ALTER TABLE `reviews_moderation_flags`
    ADD CONSTRAINT `reviews_moderation_flags_ibfk_2`
        FOREIGN KEY `reviews_moderation_flags_ibfk_2` (`user_id`)
        REFERENCES `users` (`id`)
        ON DELETE CASCADE;

SET FOREIGN_KEY_CHECKS=1;
