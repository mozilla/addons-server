#!/usr/bin/env python
import os
from string import Template

CRONS = {}

COMMON = {
    'MANAGE': '/usr/bin/python26 manage.py',
    'Z_CRON': '$DJANGO cron',
}

CRONS['preview'] = {
    'ZAMBONI': '/data/amo_python/src/preview/zamboni',
    'REMORA': 'cd /data/amo/www/addons.mozilla.org-preview/bin',
    'DJANGO': 'cd $ZAMBONI; $MANAGE',
}

CRONS['prod'] = {
    'ZAMBONI': '/data/amo_python/src/prod/zamboni',
    'REMORA': 'apache cd /data/amo/www/addons.mozilla.org-remora/bin',
    'DJANGO': 'apache cd $ZAMBONI; $MANAGE',
}

# Update each dict with the values from common.
for key, dict_ in CRONS.items():
    dict_.update(COMMON)

# Do any interpolation inside the keys.
for dict_ in CRONS.values():
    while 1:
        changed = False
        for key, val in dict_.items():
            new = Template(val).substitute(dict_)
            if new != val:
                changed = True
                dict_[key] = new
        if not changed:
            break


# TODO(andym) remove migrate_approvals when zamboni editor tools are live
cron = """\
#
# !!AUTO-GENERATED!!  Edit scripts/crontab/make-crons.py instead.
#

MAILTO=amo-developers@mozilla.org

HOME = /tmp

# Every minute!
* * * * * $Z_CRON fast_current_version
* * * * * $Z_CRON migrate_collection_users

# Every 20 minutes.
*/20 * * * * $Z_CRON check_queues
*/20 * * * * $Z_CRON migrate_approvals

# Every 30 minutes.
*/30 * * * * $Z_CRON tag_jetpacks
*/30 * * * * $Z_CRON update_addons_current_version

#once per hour
5 * * * * $Z_CRON update_collections_subscribers
10 * * * * $REMORA; php -f maintenance.php blog
15 * * * * $REMORA; php -f update-search-views.php
20 * * * * $Z_CRON addon_last_updated
25 * * * * $Z_CRON update_collections_votes
30 * * * * $REMORA; php -f maintenance.php l10n_stats
35 * * * * $REMORA; php -f maintenance.php l10n_rss
40 * * * * $Z_CRON fetch_ryf_blog
45 * * * * $Z_CRON update_addon_appsupport
50 * * * * $Z_CRON cleanup_extracted_file


#every 3 hours
20 */3 * * * $REMORA; php -f compatibility_report.php

#twice per day
25 1,13 * * * $REMORA; /usr/bin/python26 import-personas.py
# Add slugs after we get all the new personas.
25 2,14 * * * $Z_CRON addons_add_slugs
45 2,14 * * * $Z_CRON give_personas_versions
25 3,15 * * * $Z_CRON update_addons_collections_downloads
25 8,20 * * * $Z_CRON update_collections_total
25 9,21 * * * $Z_CRON hide_disabled_files

#once per day
30 1 * * * $Z_CRON update_user_ratings
30 2 * * * $Z_CRON addon_reviews_ratings
30 3 * * * $DJANGO cleanup
30 4 * * * $DJANGO clean_redis
30 5 * * * $REMORA; php -f maintenance.php expired_resetcode
30 6 * * * $REMORA; php -f maintenance.php category_totals
30 7 * * * $REMORA; php -f maintenance.php collection_subscribers
30 8 * * * $REMORA; /usr/bin/python26 maintenance.py personas_adu
30 9 * * * $REMORA; /usr/bin/python26 maintenance.py share_count_totals
30 10 * * * $Z_CRON recs
30 20 * * * $Z_CRON update_perf
30 22 * * * $Z_CRON deliver_hotness
30 23 * * * $Z_CRON collection_meta
40 23 * * * $Z_CRON update_compat_info_for_fx4
45 23 * * * $DJANGO dump_apps
50 23 * * * $Z_CRON migrate_admin_logs

#Once per day after 2100 PST (after metrics is done)
35 21 * * * $Z_CRON update_addon_download_totals
40 21 * * * $REMORA; /usr/bin/python26 maintenance.py weekly
35 22 * * * $Z_CRON update_global_totals
40 22 * * * $Z_CRON update_addon_average_daily_users

# Once per week
45 23 * * 4 $REMORA; php -f maintenance.php unconfirmed

MAILTO=root
"""


def main():
    for key, vals in CRONS.items():
        path = os.path.join(os.path.dirname(__file__), key)
        open(path, 'w').write(Template(cron).substitute(vals))


if __name__ == '__main__':
    main()
