CREATE TABLE `refunds` (
    `id` int(11) unsigned NOT NULL AUTO_INCREMENT,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `contribution_id` int(11) unsigned NOT NULL,
    `status` int(11) unsigned NOT NULL,
    `refund_reason` longtext NOT NULL,
    `rejection_reason` longtext NOT NULL,
    `requested` datetime DEFAULT NULL,
    `approved` datetime DEFAULT NULL,
    `declined` datetime DEFAULT NULL,
    PRIMARY KEY (`id`),
    KEY `refunds_contribution_id_idx` (`contribution_id`),
    KEY `refunds_status_idx` (`status`),
    KEY `refunds_requested_idx` (`requested`),
    KEY `refunds_approved_idx` (`approved`),
    KEY `refunds_declined_idx` (`declined`),
    CONSTRAINT `contribution_id_pk`
        FOREIGN KEY (`contribution_id`)
        REFERENCES `stats_contributions` (`id`)
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;
