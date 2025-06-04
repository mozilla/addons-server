import json


"""
Keys are define either as a tuple of (str, value-type, default) or a str.
`value-type` currently supported in get_config are int, json, and str (the default).
The default `default` is None.
"""

BLOCKLIST_BASE_REPLACE_THRESHOLD = 'blocklist_base_replace_threshold', int, 5_000

BLOCKLIST_MLBF_BASE_ID = 'blocklist_mlbf_base_id', json, None

BLOCKLIST_MLBF_BASE_ID_SOFT_BLOCKED = 'blocklist_mlbf_base_id_soft_blocked', json, None

BLOCKLIST_MLBF_BASE_ID_BLOCKED = 'blocklist_mlbf_base_id_blocked', json, None

# Used to track recent mlbf ids
BLOCKLIST_MLBF_TIME = 'blocklist_mlbf_generation_time', json, None

# Target number of reviews each task that adds extra versions to the review
# queue will add per day.
EXTRA_REVIEW_TARGET_PER_DAY = 'extra-review-target-per-day', int, 8

INITIAL_AUTO_APPROVAL_DELAY_FOR_LISTED = (
    'INITIAL_AUTO_APPROVAL_DELAY_FOR_LISTED',
    int,
    24 * 60 * 60,
)

INITIAL_DELAY_FOR_UNLISTED = 'INITIAL_DELAY_FOR_UNLISTED', int, 0

LAST_DEV_AGREEMENT_CHANGE_DATE = 'last_dev_agreement_change_date'

REVIEWERS_MOTD = 'reviewers_review_motd'

SITE_NOTICE = 'site_notice'

SUBMIT_NOTIFICATION_WARNING = 'submit_notification_warning'

SUBMIT_NOTIFICATION_WARNING_PRE_REVIEW = 'submit_notification_warning_pre_review'

UPCOMING_DUE_DATE_CUT_OFF_DAYS = 'upcoming-due-date-cut-off-days', int, 2

KEYS = [
    val[0] if isinstance(val, tuple) else val
    for val in vars().values()
    if isinstance(val, (str, tuple))
]
