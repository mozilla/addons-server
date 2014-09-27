DROP TABLE IF EXISTS `log_activity_addon_mkt`;
DROP TABLE IF EXISTS `log_activity_app_mkt`;
DROP TABLE IF EXISTS `log_activity_attachment_mkt`;
DROP TABLE IF EXISTS `log_activity_comment_mkt`;
DROP TABLE IF EXISTS `log_activity_group_mkt`;
DROP TABLE IF EXISTS `log_activity_user_mkt`;
DROP TABLE IF EXISTS `log_activity_version_mkt`;
DROP TABLE IF EXISTS `log_activity_mkt`;
DROP TABLE IF EXISTS `mkt_feed_app`;
DROP TABLE IF EXISTS `mkt_feed_item`;
DROP TABLE IF EXISTS `zadmin_siteevent_mkt`;
DROP TABLE IF EXISTS `webapps_contentrating`;
DROP TABLE IF EXISTS `webapps_geodata`;
DROP TABLE IF EXISTS `webapps_iarc_info`;
DROP TABLE IF EXISTS `webapps_rating_descriptors`;
DROP TABLE IF EXISTS `webapps_rating_interactives`;
DROP TABLE IF EXISTS `app_manifest`;
DROP TABLE IF EXISTS `comm_attachments`;
DROP TABLE IF EXISTS `comm_notes_read`;
DROP TABLE IF EXISTS `comm_thread_cc`;
DROP TABLE IF EXISTS `comm_thread_notes`;
DROP TABLE IF EXISTS `comm_thread_tokens`;
DROP TABLE IF EXISTS `comm_threads`;

-- Remove point types that only apply to Marketplace:
-- https://github.com/mozilla/zamboni/blob/master/mkt/constants/base.py#L249
DELETE
    FROM reviewer_scores
    WHERE note_key IN (70, 71, 72, 73, 81);

-- Remove temporary manual point adjustments for Marketplace reviews
DELETE
    FROM reviewer_scores
    WHERE
        note_key = 0 AND
        note LIKE '% remove app review points';
