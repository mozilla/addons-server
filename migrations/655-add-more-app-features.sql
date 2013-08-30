ALTER TABLE `addons_features`
    ADD COLUMN `has_camera` bool NOT NULL,
    ADD COLUMN `has_mic` bool NOT NULL,
    ADD COLUMN `has_screen_capture` bool NOT NULL,
    ADD COLUMN `has_webrtc_media` bool NOT NULL,
    ADD COLUMN `has_webrtc_data` bool NOT NULL,
    ADD COLUMN `has_webrtc_peer` bool NOT NULL,
    ADD COLUMN `has_speech_syn` bool NOT NULL,
    ADD COLUMN `has_speech_rec` bool NOT NULL,
    ADD COLUMN `has_pointer_lock` bool NOT NULL,
    ADD COLUMN `has_notification` bool NOT NULL,
    ADD COLUMN `has_alarm` bool NOT NULL,
    ADD COLUMN `has_systemxhr` bool NOT NULL,
    ADD COLUMN `has_tcpsocket` bool NOT NULL;
