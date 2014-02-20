# Crons are run in UTC time!

MAILTO=amo-developers@mozilla.org

HOME=/tmp

# Every minute!
* * * * * %(z_cron)s fast_current_version

# Every 30 minutes.
*/30 * * * * %(z_cron)s update_addons_current_version

#once per hour
5 * * * * %(z_cron)s update_collections_subscribers
10 * * * * %(z_cron)s update_blog_posts
20 * * * * %(z_cron)s addon_last_updated
25 * * * * %(z_cron)s update_collections_votes
45 * * * * %(z_cron)s update_addon_appsupport
50 * * * * %(z_cron)s cleanup_extracted_file
55 * * * * %(z_cron)s unhide_disabled_files


#every 3 hours
20 */3 * * * %(z_cron)s compatibility_report

#every 4 hours
40 */4 * * * %(django)s clean_redis

#twice per day
# Use system python to use an older version of sqlalchemy than what is in our venv
# Add slugs after we get all the new personas.
# commented out 2013-03-28, clouserw
#25 10,22 * * * %(z_cron)s addons_add_slugs
# commented out 2013-03-28, clouserw
#45 2,14 * * * %(z_cron)s give_personas_versions
25 16,4 * * * %(z_cron)s update_collections_total
25 17,5 * * * %(z_cron)s hide_disabled_files

#once per day
05 8 * * * %(z_cron)s email_daily_ratings --settings=settings_local_mkt
15 8 * * * %(z_cron)s process_iarc_changes --settings=settings_local_mkt
30 8 * * * %(z_cron)s dump_user_installs_cron --settings=settings_local_mkt
00 9 * * * %(z_cron)s update_app_downloads --settings=settings_local_mkt
30 9 * * * %(z_cron)s update_user_ratings
50 9 * * * %(z_cron)s gc
45 9 * * * %(z_cron)s mkt_gc --settings=settings_local_mkt
45 9 * * * %(z_cron)s clean_old_signed --settings=settings_local_mkt
45 10 * * * %(django)s process_addons --task=update_manifests --settings=settings_local_mkt
45 11 * * * %(django)s process_addons --task=dump_apps --settings=settings_local_mkt
30 12 * * * %(z_cron)s cleanup_synced_collections
30 13 * * * %(z_cron)s expired_resetcode
30 14 * * * %(z_cron)s category_totals
30 15 * * * %(z_cron)s collection_subscribers
# commented out 2013-03-28, clouserw
#30 16 * * * %(z_cron)s personas_adu
30 17 * * * %(z_cron)s share_count_totals
30 18 * * * %(z_cron)s recs
30 6 * * * %(z_cron)s deliver_hotness
45 7 * * * %(django)s dump_apps

# Collect visitor stats from Google Analytics once per day.
50 10 * * * %(z_cron)s update_google_analytics --settings=settings_local_mkt

#Once per day after 2100 PST (after metrics is done)
35 5 * * * %(z_cron)s update_addon_download_totals
40 5 * * * %(z_cron)s weekly_downloads
35 6 * * * %(z_cron)s update_global_totals
40 6 * * * %(z_cron)s update_addon_average_daily_users
30 7 * * * %(z_cron)s index_latest_stats
45 7 * * * %(z_cron)s update_addons_collections_downloads
50 7 * * * %(z_cron)s update_daily_theme_user_counts

# Once per week
45 7 * * 4 %(z_cron)s unconfirmed

MAILTO=root
