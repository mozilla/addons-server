ALTER TABLE `addons`
    MODIFY `externalsoftware` tinyint(1) DEFAULT 0,
    MODIFY `auto_repackage` tinyint(1) DEFAULT 0;
