# Crons are run in UTC time!

MAILTO=amo-developers@mozilla.org
DJANGO_SETTINGS_MODULE='settings_local'

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

#twice per day
25 16,4 * * * %(z_cron)s update_collections_total
25 17,5 * * * %(z_cron)s hide_disabled_files
25 18,6 * * * %(z_cron)s cleanup_image_files

#once per day
30 9 * * * %(z_cron)s update_user_ratings
30 12 * * * %(z_cron)s cleanup_synced_collections
30 14 * * * %(z_cron)s category_totals
30 15 * * * %(z_cron)s collection_subscribers
30 17 * * * %(z_cron)s share_count_totals
30 18 * * * %(z_cron)s recs
0 22 * * * %(z_cron)s gc
30 6 * * * %(z_cron)s deliver_hotness

# Collect visitor stats from Google Analytics once per day.
50 10 * * * %(z_cron)s update_google_analytics

# Update ADI metrics from HIVE.
# Once per day after 1000 UTC (after hive queries + transfert is done)
30 10 * * * %(django)s update_counts_from_file
00 11 * * * %(django)s download_counts_from_file
05 11 * * * %(django)s theme_update_counts_from_hive
30 11 * * * %(django)s theme_update_counts_from_file
30 12 * * * %(django)s update_theme_popularity_movers

# Once per day after metrics is done (see above)
35 11 * * * %(z_cron)s update_addon_download_totals
40 11 * * * %(z_cron)s weekly_downloads
35 12 * * * %(z_cron)s update_global_totals
40 12 * * * %(z_cron)s update_addon_average_daily_users
30 13 * * * %(z_cron)s index_latest_stats
45 13 * * * %(z_cron)s update_addons_collections_downloads
50 13 * * * %(z_cron)s update_daily_theme_user_counts

# Once per week
45 7 * * 4 %(z_cron)s unconfirmed

MAILTO=root
