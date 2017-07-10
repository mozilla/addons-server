-- is_restart_required replaces the old no_restart field. It's the exact opposite.
ALTER TABLE `files`
    ADD COLUMN `is_restart_required` bool NOT NULL,
    MODIFY `no_restart` bool;  -- Allow nulls to prepare for column removal next push.
UPDATE `files` SET `is_restart_required` = NOT `no_restart`;
