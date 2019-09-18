ALTER TABLE `log_activity_emails`
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `messageid` varchar(255) NOT NULL;
