ALTER TABLE `cannedresponses`
    MODIFY `id` int(10) unsigned NOT NULL,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `name` varchar(255) NOT NULL,
    MODIFY `response` longtext NOT NULL,
    MODIFY `sort_group` varchar(255) NOT NULL,
    MODIFY `category` int(10) unsigned NOT NULL,
    ADD KEY `cannedresponses_type_8f3c32fc` (`type`);
