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
    ADD UNIQUE KEY `supportemail` (`supportemail`),
    ADD UNIQUE KEY `homepage` (`homepage`),
    ADD UNIQUE KEY `description` (`description`),
    ADD UNIQUE KEY `summary` (`summary`),
    ADD UNIQUE KEY `developercomments` (`developercomments`),
    ADD UNIQUE KEY `eula` (`eula`),
    ADD UNIQUE KEY `privacypolicy` (`privacypolicy`);
