from django.utils.translation import gettext_lazy as _

from .base import ADDON_ANY, ADDON_EXTENSION, ADDON_STATICTHEME


# Reviewer Tools
REVIEWER_VIEWING_INTERVAL = 8  # How often we ping for "who's watching?"
REVIEWER_REVIEW_LOCK_LIMIT = 3  # How many pages can a reviewer "watch"
# Default delayed rejection period in days
REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT = 14

REVIEWER_STANDARD_REVIEW_TIME = 4  # How many (week)days we expect to review within

# Types of Canned Responses for reviewer tools.
CANNED_RESPONSE_TYPE_ADDON = 1
CANNED_RESPONSE_TYPE_THEME = 2
CANNED_RESPONSE_TYPE_PERSONA = 3

CANNED_RESPONSE_TYPE_CHOICES = {
    CANNED_RESPONSE_TYPE_ADDON: _('Add-on'),
    CANNED_RESPONSE_TYPE_THEME: _('Static Theme'),
    CANNED_RESPONSE_TYPE_PERSONA: _('Persona'),
}

# Categories to group canned responses and make them easier to look through
CANNED_RESPONSE_CATEGORY_OTHER = 1
CANNED_RESPONSE_CATEGORY_SECURITY = 2
CANNED_RESPONSE_CATEGORY_PRIVACY = 3
CANNED_RESPONSE_CATEGORY_DEVELOPMENT_PRACTICES = 4

CANNED_RESPONSE_CATEGORY_CHOICES = {
    CANNED_RESPONSE_CATEGORY_OTHER: _('Other'),
    CANNED_RESPONSE_CATEGORY_SECURITY: _('Security'),
    CANNED_RESPONSE_CATEGORY_PRIVACY: _('Privacy'),
    CANNED_RESPONSE_CATEGORY_DEVELOPMENT_PRACTICES: _('Development Practices'),
}

# Risk tiers for post-review weight.
POST_REVIEW_WEIGHT_HIGHEST_RISK = 275
POST_REVIEW_WEIGHT_HIGH_RISK = 175
POST_REVIEW_WEIGHT_MEDIUM_RISK = 90

REPUTATION_CHOICES = {
    0: _('No Reputation'),
    1: _('Good (1)'),
    2: _('Very Good (2)'),
    3: _('Excellent (3)'),
}

# Review queue pagination
REVIEWS_PER_PAGE = 200
REVIEWS_PER_PAGE_MAX = 400

ACTION_MOREINFO = 0
ACTION_FLAG = 1
ACTION_DUPLICATE = 2
ACTION_REJECT = 3
ACTION_APPROVE = 4
REVIEW_ACTIONS = {
    ACTION_MOREINFO: _('Request More Info'),
    ACTION_FLAG: _('Flag'),
    ACTION_DUPLICATE: _('Duplicate'),
    ACTION_REJECT: _('Reject'),
    ACTION_APPROVE: _('Approve'),
}

WOULD_NOT_HAVE_BEEN_AUTO_APPROVED = 0
WOULD_HAVE_BEEN_AUTO_APPROVED = 1
AUTO_APPROVED = 2
NOT_AUTO_APPROVED = 3

AUTO_APPROVAL_VERDICT_CHOICES = (
    (
        WOULD_NOT_HAVE_BEEN_AUTO_APPROVED,
        'Would have been auto-approved (dry-run mode was in effect)',
    ),
    (
        WOULD_HAVE_BEEN_AUTO_APPROVED,
        'Would *not* have been auto-approved (dry-run mode was in effect)',
    ),
    (AUTO_APPROVED, 'Was auto-approved'),
    (NOT_AUTO_APPROVED, 'Was *not* auto-approved'),
)

# Types of Add-ons for Reasons.
REASON_ADDON_TYPE_CHOICES = {
    ADDON_ANY: _('All'),
    ADDON_EXTENSION: _('Extension'),
    ADDON_STATICTHEME: _('Theme'),
}
