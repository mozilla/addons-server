-- Model missing for table: compat_override_range
DROP TABLE IF EXISTS  `compat_override_range`;
-- Model missing for table: compat_override
DROP TABLE IF EXISTS `compat_override`;
-- Model missing for table: email_preview
DROP TABLE IF EXISTS  `email_preview`;
-- Model missing for table: incompatible_versions
DROP TABLE IF EXISTS  `incompatible_versions`;
-- Model missing for table: product_details_productdetailsfile
DROP TABLE IF EXISTS  `product_details_productdetailsfile`;
-- Model missing for table: webext_permission_descriptions
DROP TABLE  IF EXISTS `webext_permission_descriptions`;
-- Model missing for table: zadmin_siteevent
DROP TABLE  IF EXISTS `zadmin_siteevent`;

ALTER TABLE `abuse_reports`
    MODIFY `addon_id` int(10) unsigned DEFAULT NULL,
    DROP FOREIGN KEY `reporter_id_refs_id_12d88e23`,
    DROP FOREIGN KEY `user_id_refs_id_12d88e23`,
    DROP FOREIGN KEY `addon_id_refs_id_2b6ff2a7`,
    DROP KEY `created_idx`;
ALTER TABLE `abuse_reports`
    ADD CONSTRAINT `abuse_reports_addon_id_f15faa13_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`),
    ADD CONSTRAINT `abuse_reports_reporter_id_e5b6b72a_fk_users_id` FOREIGN KEY (`reporter_id`) REFERENCES `users` (`id`),
    ADD CONSTRAINT `abuse_reports_user_id_67401662_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `addons`
    MODIFY `defaultlocale` varchar(10) NOT NULL,
    MODIFY `icontype` varchar(25) NOT NULL,
    MODIFY `weeklydownloads` int(10) unsigned NOT NULL,
    MODIFY `hotness` double NOT NULL,
    MODIFY `experimental` tinyint(1) NOT NULL,
    DROP FOREIGN KEY `addons_ibfk_2`,  /* name */
    DROP FOREIGN KEY `addons_ibfk_3`,  /* homepage */
    DROP FOREIGN KEY `addons_ibfk_4`,  /* description */
    DROP FOREIGN KEY `addons_ibfk_5`,  /* summary */
    DROP FOREIGN KEY `addons_ibfk_6`,  /* developercomments */
    DROP FOREIGN KEY `addons_ibfk_7`,  /* eula */
    DROP FOREIGN KEY `addons_ibfk_8`,  /* privacypolicy */
    DROP FOREIGN KEY `addons_ibfk_9`,  /* supporturl */
    DROP FOREIGN KEY `addons_ibfk_10`,  /* supportemail */
    DROP FOREIGN KEY `addons_ibfk_14`,  /* current_version */
    DROP KEY `addontype_id`,
    DROP KEY `status`,
    DROP KEY `inactive`,
    DROP KEY `supporturl`,
    DROP KEY `supportemail`,
    DROP KEY `target_locale`,
    DROP KEY `bayesianrating`,
    DROP KEY `last_updated`,
    DROP KEY `current_version`,
    DROP KEY `created_idx`,
    DROP KEY `modified_idx`,
    DROP KEY `weeklydownloads_idx`,
    DROP KEY `rating_type_idx`,
    DROP KEY `created_type_idx`,
    DROP KEY `modified_type_idx`,
    DROP KEY `downloads_type_idx`,
    DROP KEY `last_updated_type_idx`,
    DROP KEY `type_status_inactive_idx`,
    DROP KEY `hotness_idx`,
    DROP KEY `visible_idx`,  /* (`addontype_id`,`status`,`inactive`,`current_version`) - note: no replacement */
    DROP KEY `adus_type_idx`,
    DROP KEY `name_2`;  /* (`name`,`status`,`addontype_id`) - note: no replacement */
ALTER TABLE `addons`
    ADD CONSTRAINT `addons_name_78bce5d2_fk_translations_id` FOREIGN KEY (`name`) REFERENCES `translations` (`id`),
    ADD CONSTRAINT `addons_homepage_f34e15ae_fk_translations_id` FOREIGN KEY (`homepage`) REFERENCES `translations` (`id`),
    ADD CONSTRAINT `addons_description_2300852e_fk_translations_id` FOREIGN KEY (`description`) REFERENCES `translations` (`id`),
    ADD CONSTRAINT `addons_summary_0d397f7c_fk_translations_id` FOREIGN KEY (`summary`) REFERENCES `translations` (`id`),
    ADD CONSTRAINT `addons_developercomments_b365508d_fk_translations_id` FOREIGN KEY (`developercomments`) REFERENCES `translations` (`id`),
    ADD CONSTRAINT `addons_eula_62f9d8e4_fk_translations_id` FOREIGN KEY (`eula`) REFERENCES `translations` (`id`),
    ADD CONSTRAINT `addons_privacypolicy_5e0b364a_fk_translations_id` FOREIGN KEY (`privacypolicy`) REFERENCES `translations` (`id`),
    ADD CONSTRAINT `addons_supporturl_1101e07c_fk_translations_id` FOREIGN KEY (`supporturl`) REFERENCES `translations` (`id`),
    ADD CONSTRAINT `addons_supportemail_da41fe48_fk_translations_id` FOREIGN KEY (`supportemail`) REFERENCES `translations` (`id`),
    ADD CONSTRAINT `addons_current_version_5a2c8cb3_fk_versions_id` FOREIGN KEY (`current_version`) REFERENCES `versions` (`id`),
    ADD KEY `addons_status_2e8bf8cf` (`status`),
    ADD KEY `addons_inactive_6dd9d25c` (`inactive`),
    ADD UNIQUE KEY `supporturl` (`supporturl`),
    ADD UNIQUE KEY `supportemail` (`supportemail`),
    ADD KEY `addons_target_locale_54ba59a9` (`target_locale`),
    ADD KEY `addons_bayesianrating_6985fcf2` (`bayesianrating`),
    ADD KEY `addons_last_updated_67632754` (`last_updated`),
    ADD KEY `addons_weeklydownloads_cba91d4f` (`weeklydownloads`),
    ADD KEY `addons_bayesianrating_addontype_id_35b741a7_idx` (`bayesianrating`,`addontype_id`),
    ADD KEY `addons_created_addontype_id_c63f7236_idx` (`created`,`addontype_id`),
    ADD KEY `addons_weeklydownloads_addontype_id_7edd3017_idx` (`weeklydownloads`,`addontype_id`),
    ADD KEY `addons_last_updated_addontype_id_0e95f7e0_idx` (`last_updated`,`addontype_id`),
    ADD KEY `addons_addontype_id_status_inactive_c80d48ba_idx` (`addontype_id`,`status`,`inactive`),
    ADD KEY `addons_hotness_ebbe8244` (`hotness`),
    ADD KEY `addons_average_daily_users_addontype_id_88e99cf4_idx` (`average_daily_users`,`addontype_id`),
    ADD UNIQUE KEY `homepage` (`homepage`),
    ADD UNIQUE KEY `description` (`description`),
    ADD UNIQUE KEY `summary` (`summary`),
    ADD UNIQUE KEY `developercomments` (`developercomments`),
    ADD UNIQUE KEY `eula` (`eula`),
    ADD UNIQUE KEY `privacypolicy` (`privacypolicy`);

ALTER TABLE `addons_addonapprovalscounter`
    DROP FOREIGN KEY addon_id_refs_id_8fcb7166;
ALTER TABLE `addons_addonapprovalscounter`
    ADD CONSTRAINT `addons_addonapprovalscounter_addon_id_4a0a4308_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);

ALTER TABLE `addons_addonreviewerflags`
    MODIFY `auto_approval_disabled` tinyint(1) NOT NULL,
    MODIFY `notified_about_expiring_info_request` tinyint(1) NOT NULL,
    DROP FOREIGN KEY `addon_id_refs_id_7a280313`;
ALTER TABLE `addons_addonreviewerflags`
    ADD CONSTRAINT `addons_addonreviewerflags_addon_id_d8b2a376_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);

ALTER TABLE `addons_categories`
    MODIFY `addon_id` int(10) unsigned NOT NULL,
    MODIFY `category_id` int(10) unsigned NOT NULL,
    MODIFY `feature` tinyint(1) NOT NULL,
    DROP KEY `addon_id`,
    DROP KEY `category_addon_idx`,
    DROP KEY `feature_addon_idx`,
    DROP FOREIGN KEY `addons_categories_ibfk_3`,  /* addons.id */
    DROP FOREIGN KEY `addons_categories_ibfk_4`;  /* categories.id */
ALTER TABLE `addons_categories`
    ADD UNIQUE KEY `addons_categories_addon_id_category_id_3cadf0f5_uniq` (`addon_id`,`category_id`),
    ADD CONSTRAINT `addons_categories_addon_id_9d915915_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`),
    ADD CONSTRAINT `addons_categories_category_id_f4f5c093_fk_categories_id` FOREIGN KEY (`category_id`) REFERENCES `categories` (`id`);

ALTER TABLE `addons_collections`
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY  `modified` datetime(6) NOT NULL,
    MODIFY `addon_id` int(10) unsigned NOT NULL,
    MODIFY `collection_id` int(10) unsigned NOT NULL,
    MODIFY `comments` int(10) unsigned DEFAULT NULL,
    MODIFY `ordering` int(10) unsigned NOT NULL,
    DROP `added`,
    DROP `category`,
    DROP `downloads`,
    DROP FOREIGN KEY `addons_collections_ibfk_1`,  /* addons.id */
    DROP FOREIGN KEY `addons_collections_ibfk_2`,  /* collections.id */
    DROP FOREIGN KEY `addons_collections_ibfk_3`,  /* users.id */
    DROP FOREIGN KEY `addons_collections_ibfk_4`,  /* comments>translations.id */
    DROP KEY `addon_id_2`,
    DROP KEY `created_idx`,
    DROP KEY `addon_id`,
    DROP KEY `collection_id`,
    DROP KEY `user_id`,
    DROP KEY `comments`;
ALTER TABLE `addons_collections`
    ADD CONSTRAINT `addons_collections_addon_id_bbc33022_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`),
    ADD CONSTRAINT `addons_collections_collection_id_68098c79_fk_collections_id` FOREIGN KEY (`collection_id`) REFERENCES `collections` (`id`),
    ADD CONSTRAINT `addons_collections_user_id_f042641b_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
    ADD CONSTRAINT `addons_collections_comments_3640122d_fk_translations_id` FOREIGN KEY (`comments`) REFERENCES `translations` (`id`),
    ADD UNIQUE KEY `addons_collections_addon_id_collection_id_a13816d9_uniq` (`addon_id`,`collection_id`),
    ADD UNIQUE KEY `comments` (`comments`);

ALTER TABLE `addons_denied_slug`
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL;

ALTER TABLE `reviews`
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `id` int(10) unsigned NOT NULL,
    MODIFY `version_id` int(10) unsigned DEFAULT NULL,
    MODIFY `user_id` int(11) NOT NULL,
    MODIFY `reply_to` int(10) unsigned DEFAULT NULL,
    MODIFY `rating` smallint(5) unsigned DEFAULT NULL,
    MODIFY `editorreview` tinyint(1) NOT NULL,
    MODIFY `flag` tinyint(1) NOT NULL,
    MODIFY `ip_address` varchar(255) NOT NULL,
    MODIFY `addon_id` int(10) unsigned NOT NULL,
    MODIFY `previous_count` int(10) unsigned NOT NULL,
    MODIFY `is_latest` tinyint(1) NOT NULL,
    MODIFY `deleted` tinyint(1) NOT NULL,
    DROP FOREIGN KEY `reviews_ibfk_4`,  /* The fk for the body column */
    DROP FOREIGN KEY `reviews_ibfk_5`,  /* addons.id */
    DROP FOREIGN KEY `reviews_reply`,  /* reply_to fk */
    DROP FOREIGN KEY `reviews_ibfk_2`,  /* users.id */
    DROP FOREIGN KEY `reviews_ibfk_1`,  /* versions.id */
    DROP KEY `one_review_per_user`,  /* (`version_id`,`user_id`,`reply_to`) note: no replacement */
    DROP KEY `version_id`,
    DROP KEY `reviews_ibfk_2`,  /* users.id` */
    DROP KEY `addon_id`,
    DROP KEY `latest_reviews`;  /* (`reply_to`,`is_latest`,`addon_id`,`created`), note: no replacement */
ALTER TABLE `reviews`
    DROP `body`,
    ADD CONSTRAINT `reviews_addon_id_80638543_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`),
    ADD CONSTRAINT `reviews_reply_to_3e3e5a19_fk_reviews_id` FOREIGN KEY (`reply_to`) REFERENCES `reviews` (`id`),
    ADD CONSTRAINT `reviews_user_id_c23b0903_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
    ADD CONSTRAINT `reviews_version_id_abde965e_fk_versions_id` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`);
