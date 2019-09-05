ALTER TABLE `fake_email`
    MODIFY `message` longtext NOT NULL,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL;
