ALTER TABLE waffle_flag_amo_users
    DROP FOREIGN KEY user_id_refs_id_bae2dfc2,
    CHANGE COLUMN user_id userprofile_id int(11) unsigned NOT NULL;

ALTER TABLE waffle_flag_amo_users
    ADD CONSTRAINT flag_userprofile_id FOREIGN KEY (userprofile_id) REFERENCES users (id);
