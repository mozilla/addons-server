from olympia.amo.enum import StrEnumChoices

from .base import ADDON_ANY, ADDON_EXTENSION, ADDON_STATICTHEME


# Reviewer Tools
REVIEWER_VIEWING_INTERVAL = 8  # How often we ping for "who's watching?"
REVIEWER_REVIEW_LOCK_LIMIT = 3  # How many pages can a reviewer "watch"
# Default delayed rejection period in days
REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT = 30

REVIEWER_STANDARD_REVIEW_TIME = 3  # How many (week)days we expect to review within
REVIEWER_STANDARD_REPLY_TIME = 2  # How many (week)days we expect to reply within

# Risk tiers for post-review weight.
POST_REVIEW_WEIGHT_HIGHEST_RISK = 275
POST_REVIEW_WEIGHT_HIGH_RISK = 175
POST_REVIEW_WEIGHT_MEDIUM_RISK = 90

REPUTATION_CHOICES = {
    0: 'No Reputation',
    1: 'Good (1)',
    2: 'Very Good (2)',
    3: 'Excellent (3)',
}

# Review queue pagination
REVIEWS_PER_PAGE = 200
REVIEWS_PER_PAGE_MAX = 400
VERSIONS_PER_REVIEW_PAGE = 10
MAX_VERSIONS_SHOWN_INLINE = 10

ACTION_MOREINFO = 0
ACTION_FLAG = 1
ACTION_DUPLICATE = 2
ACTION_REJECT = 3
ACTION_APPROVE = 4
REVIEW_ACTIONS = {
    ACTION_MOREINFO: 'Request More Info',
    ACTION_FLAG: 'Flag',
    ACTION_DUPLICATE: 'Duplicate',
    ACTION_REJECT: 'Reject',
    ACTION_APPROVE: 'Approve',
}

WOULD_NOT_HAVE_BEEN_AUTO_APPROVED = 0
WOULD_HAVE_BEEN_AUTO_APPROVED = 1
AUTO_APPROVED = 2
NOT_AUTO_APPROVED = 3

AUTO_APPROVAL_VERDICT_CHOICES = (
    (
        WOULD_NOT_HAVE_BEEN_AUTO_APPROVED,
        'Would *not* have been auto-approved (dry-run mode was in effect)',
    ),
    (
        WOULD_HAVE_BEEN_AUTO_APPROVED,
        'Would have been auto-approved (dry-run mode was in effect)',
    ),
    (AUTO_APPROVED, 'Was auto-approved'),
    (NOT_AUTO_APPROVED, 'Was *not* auto-approved'),
)

# Types of Add-ons for Reasons.
REASON_ADDON_TYPE_CHOICES = {
    ADDON_ANY: 'All',
    ADDON_EXTENSION: 'Extension',
    ADDON_STATICTHEME: 'Theme',
}


class HELD_DECISION_CHOICES(StrEnumChoices):
    YES = 'yes', 'Proceed with action'
    NO = 'no', 'Approve content instead'
    CANCEL = 'cancel', 'Cancel and enqueue in Reviewer Tools'


HELD_DECISION_CHOICES.add_subset('ADDON', ('YES', 'CANCEL'))
HELD_DECISION_CHOICES.add_subset('OTHER', ('YES', 'NO'))
