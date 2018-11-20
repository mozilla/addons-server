# Crons are run in UTC time!

MAILTO=amo-crons@mozilla.com
DJANGO_SETTINGS_MODULE='settings_local'

HOME=/tmp

# Every 5 minutes
*/5 * * * * %(django)s auto_approve

#once per hour
10 * * * * %(z_cron)s update_blog_posts
15 * * * * %(django)s send_info_request_last_warning_notifications
20 * * * * %(z_cron)s addon_last_updated
45 * * * * %(z_cron)s update_addon_appsupport
50 * * * * %(z_cron)s cleanup_extracted_file
55 * * * * %(z_cron)s unhide_disabled_files

#every 3 hours
20 */3 * * * %(z_cron)s compatibility_report

#twice per day
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

# Update ADI metrics from S3.
# Once per day after 0800 UTC
30 9 * * * %(django)s update_counts_from_file
00 10 * * * %(django)s download_counts_from_file
15 10 * * * %(django)s theme_update_counts_from_file
30 10 * * * %(django)s update_theme_popularity_movers

# Once per day after metrics import is done
30 10 * * * %(z_cron)s update_addon_download_totals
35 10 * * * %(z_cron)s weekly_downloads
25 11 * * * %(z_cron)s update_global_totals
30 11 * * * %(z_cron)s update_addon_average_daily_users
00 12 * * * %(z_cron)s index_latest_stats

# Once per week
0 12 * * 1 %(django)s review_reports

# Do not put crons below this line

MAILTO=root
