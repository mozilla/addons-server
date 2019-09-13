ALTER TABLE `log_activity_comment`
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    DROP KEY `activity_log_id`,
    DROP FOREIGN KEY `log_activity_comment_ibfk_1`,  /* (`activity_log_id`) REFERENCES `log_activity` (`id`)*/
    ADD KEY `log_activity_comment_activity_log_id_0ea815de_fk_log_activity_id` (`activity_log_id`),
    ADD CONSTRAINT `log_activity_comment_activity_log_id_0ea815de_fk_log_activity_id` FOREIGN KEY (`activity_log_id`) REFERENCES `log_activity` (`id`);
