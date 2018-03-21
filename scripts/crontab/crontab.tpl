# Crons are run in UTC time!

MAILTO=amo-crons@mozilla.com
DJANGO_SETTINGS_MODULE='settings_local'

HOME=/tmp

# Every 10 minutes
*/10 * * * * %(django)s auto_approve

#once per hour
5 * * * * %(z_cron)s update_collections_subscribers
10 * * * * %(z_cron)s update_blog_posts
15 * * * * %(django)s send_info_request_last_warning_notifications
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
25 16,4 * * * %(z_cron)s update_collections_total
25 17,5 * * * %(z_cron)s hide_disabled_files
25 18,6 * * * %(z_cron)s cleanup_image_files

#once per day
30 9 * * * %(z_cron)s update_user_ratings
30 14 * * * %(z_cron)s category_totals
30 15 * * * %(z_cron)s collection_subscribers
0 22 * * * %(z_cron)s gc
30 6 * * * %(z_cron)s deliver_hotness
45 7 * * * %(django)s dump_apps
0 8 * * * %(django)s update_product_details

# Once per day after metrics import is done
00 9 * * * %(z_cron)s update_addon_download_totals
05 9 * * * %(z_cron)s weekly_downloads
55 9 * * * %(z_cron)s update_global_totals
00 10 * * * %(z_cron)s update_addon_average_daily_users
30 10 * * * %(z_cron)s index_latest_stats
45 10 * * * %(z_cron)s update_addons_collections_downloads

# Update ADI metrics from S3.
# Once per day after 0800 UTC
00 8 * * * %(django)s update_counts_from_file
30 8 * * * %(django)s download_counts_from_file
45 8 * * * %(django)s theme_update_counts_from_file
00 9 * * * %(django)s update_theme_popularity_movers

# Do not put crons below this line

MAILTO=root
