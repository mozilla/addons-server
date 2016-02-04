ALTER TABLE `addon_inapp_payment`
    DROP FOREIGN KEY `contribution_id_refs_id_5d086f0`;
ALTER TABLE `addon_inapp_payment`
    ADD CONSTRAINT `contribution_id_refs_id_5d086f0`
    FOREIGN KEY (`contribution_id`) REFERENCES `stats_contributions` (`id`)
    ON DELETE CASCADE;
ALTER TABLE `addon_inapp_notice`
    DROP FOREIGN KEY `payment_id_refs_id_8a79c182`;
ALTER TABLE `addon_inapp_notice`
    ADD CONSTRAINT `payment_id_refs_id_8a79c182`
    FOREIGN KEY (`payment_id`) REFERENCES `addon_inapp_payment` (`id`)
    ON DELETE CASCADE;
