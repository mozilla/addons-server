ALTER TABLE `hero_primaryhero`
    MODIFY `is_external` tinyint(1) NOT NULL;

ALTER TABLE `hero_secondaryhero`
    DROP KEY `hero_secondaryhero_enabled_12e9da72`,  /* (`enabled`),*/
    ADD KEY `hero_secondaryhero_enabled_1a9ea03c` (`enabled`);
