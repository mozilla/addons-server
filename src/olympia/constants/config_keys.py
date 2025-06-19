import json
from dataclasses import dataclass


@dataclass
class ConfigKey:
    key: str
    default: str | None = None
    type_ = str

    def load(self, value):
        return self.type_(value)

    def dump(self, value):
        return str(value)


class IntConfigKey(ConfigKey):
    default: int | None = None
    type_ = int


class JsonConfigKey(ConfigKey):
    default: dict | list | None = None
    type_ = None

    def load(self, value):
        return json.loads(value)

    def dump(self, value):
        return json.dumps(value)


BLOCKLIST_BASE_REPLACE_THRESHOLD = IntConfigKey(
    'blocklist_base_replace_threshold', 5_000
)

BLOCKLIST_MLBF_BASE_ID = JsonConfigKey('blocklist_mlbf_base_id')

BLOCKLIST_MLBF_BASE_ID_SOFT_BLOCKED = JsonConfigKey(
    'blocklist_mlbf_base_id_soft_blocked'
)

BLOCKLIST_MLBF_BASE_ID_BLOCKED = JsonConfigKey('blocklist_mlbf_base_id_blocked')

# Used to track recent mlbf ids
BLOCKLIST_MLBF_TIME = JsonConfigKey('blocklist_mlbf_generation_time')

# Target number of reviews each task that adds extra versions to the review
# queue will add per day.
EXTRA_REVIEW_TARGET_PER_DAY = IntConfigKey('extra-review-target-per-day', 8)

INITIAL_AUTO_APPROVAL_DELAY_FOR_LISTED = IntConfigKey(
    'INITIAL_AUTO_APPROVAL_DELAY_FOR_LISTED', 24 * 60 * 60
)

INITIAL_DELAY_FOR_UNLISTED = IntConfigKey('INITIAL_DELAY_FOR_UNLISTED', 0)

LAST_DEV_AGREEMENT_CHANGE_DATE = ConfigKey('last_dev_agreement_change_date')

REVIEWERS_MOTD = ConfigKey('reviewers_review_motd')

SITE_NOTICE = ConfigKey('site_notice')

SUBMIT_NOTIFICATION_WARNING = ConfigKey('submit_notification_warning')

SUBMIT_NOTIFICATION_WARNING_PRE_REVIEW = ConfigKey(
    'submit_notification_warning_pre_review'
)

UPCOMING_DUE_DATE_CUT_OFF_DAYS = IntConfigKey('upcoming-due-date-cut-off-days', 2)

KEYS = [val.key for val in vars().values() if isinstance(val, ConfigKey)]
