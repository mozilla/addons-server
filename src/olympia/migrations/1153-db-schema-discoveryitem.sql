ALTER TABLE `discovery_discoveryitem`
    MODIFY `position` smallint(5) unsigned NOT NULL,
    MODIFY `position_china` smallint(5) unsigned NOT NULL,
    MODIFY `position_override` smallint(5) unsigned NOT NULL,
    MODIFY `recommendable` tinyint(1) NOT NULL,
    ADD KEY `discovery_discoveryitem_position_override_baa9e118` (`position_override`),
    ADD KEY `discovery_discoveryitem_recommendable_a7eb6870` (`recommendable`),
    DROP FOREIGN KEY `addon_id_refs_id_93b5ecf8`, /* (`addon_id`) REFERENCES `addons` (`id`),*/
    ADD CONSTRAINT `discovery_discoveryitem_addon_id_b9bc34ae_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
