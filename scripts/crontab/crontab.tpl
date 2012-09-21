MAILTO=amo-developers@mozilla.org

HOME=/tmp

# Every minute!
* * * * * %(z_cron)s fast_current_version
* * * * * %(z_cron)s migrate_collection_users

# Every 30 minutes.
*/30 * * * * %(z_cron)s tag_jetpacks
*/30 * * * * %(z_cron)s update_addons_current_version
*/30 * * * * %(z_cron)s reset_featured_addons
*/30 * * * * %(z_cron)s cleanup_watermarked_file

#once per hour
5 * * * * %(z_cron)s update_collections_subscribers
10 * * * * %(z_cron)s update_blog_posts
20 * * * * %(z_cron)s addon_last_updated
25 * * * * %(z_cron)s update_collections_votes
40 * * * * %(z_cron)s fetch_ryf_blog
45 * * * * %(z_cron)s update_addon_appsupport
50 * * * * %(z_cron)s cleanup_extracted_file
55 * * * * %(z_cron)s unhide_disabled_files


#every 3 hours
20 */3 * * * %(z_cron)s compatibility_report
# clouserw commented this out
#20 */3 * * * %(remora)s; php -f compatibility_report.php

#every 4 hours
40 */4 * * * %(django)s clean_redis

#twice per day
25 1,13 * * * %(remora)s; %(python)s import-personas.py
# Add slugs after we get all the new personas.
25 2,14 * * * %(z_cron)s addons_add_slugs
45 2,14 * * * %(z_cron)s give_personas_versions
25 8,20 * * * %(z_cron)s update_collections_total
25 9,21 * * * %(z_cron)s hide_disabled_files

#once per day
05 0 * * * %(z_cron)s email_daily_ratings --settings=settings_local_mkt
30 1 * * * %(z_cron)s update_user_ratings
40 1 * * * %(z_cron)s update_weekly_downloads
50 1 * * * %(z_cron)s gc
45 1 * * * %(z_cron)s mkt_gc --settings=settings_local_mkt
30 2 * * * %(z_cron)s mail_pending_refunds --settings=settings_local_mkt
45 2 * * * %(django)s process_addons --task=update_manifests --settings=settings_local_mkt
30 3 * * * %(django)s cleanup
45 3 * * * %(z_cron)s cleanup_old_signed
30 4 * * * %(z_cron)s cleanup_synced_collections
30 5 * * * %(z_cron)s expired_resetcode
30 6 * * * %(z_cron)s category_totals
30 7 * * * %(z_cron)s collection_subscribers
30 8 * * * %(z_cron)s personas_adu
30 9 * * * %(z_cron)s share_count_totals
30 10 * * * %(z_cron)s recs
30 20 * * * %(z_cron)s update_perf
30 22 * * * %(z_cron)s deliver_hotness
40 23 * * * %(z_cron)s update_compat_info_for_fx4
45 23 * * * %(django)s dump_apps
55 23 * * * %(z_cron)s clean_out_addonpremium

#Once per day after 2100 PST (after metrics is done)
35 21 * * * %(z_cron)s update_addon_download_totals
40 21 * * * %(z_cron)s weekly_downloads
35 22 * * * %(z_cron)s update_global_totals
40 22 * * * %(z_cron)s update_addon_average_daily_users
30 23 * * * %(z_cron)s index_latest_stats
35 23 * * * %(z_cron)s index_latest_mkt_stats --settings=settings_local_mkt
45 23 * * * %(z_cron)s update_addons_collections_downloads

# Once per week
45 23 * * 4 %(z_cron)s unconfirmed
35 22 * * 3 %(django)s process_addons --task=check_paypal --settings=settings_local_mkt

MAILTO=root
