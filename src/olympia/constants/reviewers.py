from django.utils.translation import ugettext_lazy as _


# Reviewer Tools
REVIEWER_VIEWING_INTERVAL = 8  # How often we ping for "who's watching?"
REVIEWER_REVIEW_LOCK_LIMIT = 3  # How many pages can a reviewer "watch"

# Types of Canned Responses for reviewer tools.
CANNED_RESPONSE_ADDON = 1
CANNED_RESPONSE_THEME = 2
CANNED_RESPONSE_PERSONA = 3

CANNED_RESPONSE_CHOICES = {
    CANNED_RESPONSE_ADDON: _('Add-on'),
    CANNED_RESPONSE_THEME: _('Static Theme'),
    CANNED_RESPONSE_PERSONA: _('Persona'),
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

# Reviewer Incentive Scores.
# Note: Don't change these since they're used as keys in the database.
REVIEWED_MANUAL = 0
REVIEWED_ADDON_FULL = 10
_REVIEWED_ADDON_PRELIM = 11  # Deprecated for new reviews - no more prelim.
REVIEWED_ADDON_UPDATE = 12
REVIEWED_DICT_FULL = 20
_REVIEWED_DICT_PRELIM = 21  # Deprecated for new reviews - no more prelim.
REVIEWED_DICT_UPDATE = 22
REVIEWED_LP_FULL = 30
_REVIEWED_LP_PRELIM = 31  # Deprecated for new reviews - no more prelim.
REVIEWED_LP_UPDATE = 32
REVIEWED_PERSONA = 40
REVIEWED_STATICTHEME = 41
# TODO: Leaving room for persona points based on queue.
REVIEWED_SEARCH_FULL = 50
_REVIEWED_SEARCH_PRELIM = 51  # Deprecated for new reviews - no more prelim.
REVIEWED_SEARCH_UPDATE = 52
REVIEWED_XUL_THEME_FULL = 60
_REVIEWED_XUL_THEME_PRELIM = 61  # Deprecated for new reviews - no more prelim.
REVIEWED_XUL_THEME_UPDATE = 62
REVIEWED_ADDON_REVIEW = 80
REVIEWED_ADDON_REVIEW_POORLY = 81
REVIEWED_CONTENT_REVIEW = 101
REVIEWED_EXTENSION_HIGHEST_RISK = 102
REVIEWED_EXTENSION_HIGH_RISK = 103
REVIEWED_EXTENSION_MEDIUM_RISK = 104
REVIEWED_EXTENSION_LOW_RISK = 105

# We need to keep the deprecated choices for existing points in the database.
REVIEWED_CHOICES = {
    REVIEWED_MANUAL: _('Manual Reviewer Points'),
    REVIEWED_ADDON_FULL: _('New Add-on Review'),
    _REVIEWED_ADDON_PRELIM: _('Preliminary Add-on Review'),
    REVIEWED_ADDON_UPDATE: _('Updated Add-on Review'),
    REVIEWED_DICT_FULL: _('New Dictionary Review'),
    _REVIEWED_DICT_PRELIM: _('Preliminary Dictionary Review'),
    REVIEWED_DICT_UPDATE: _('Updated Dictionary Review'),
    REVIEWED_LP_FULL: _('New Language Pack Review'),
    _REVIEWED_LP_PRELIM: _('Preliminary Language Pack Review'),
    REVIEWED_LP_UPDATE: _('Updated Language Pack Review'),
    REVIEWED_PERSONA: _('Theme Review'),
    REVIEWED_STATICTHEME: _('Theme (Static) Review'),
    REVIEWED_SEARCH_FULL: _('New Search Provider Review'),
    _REVIEWED_SEARCH_PRELIM: _('Preliminary Search Provider Review'),
    REVIEWED_SEARCH_UPDATE: _('Updated Search Provider Review'),
    REVIEWED_XUL_THEME_FULL: _('New Complete Theme Review'),
    _REVIEWED_XUL_THEME_PRELIM: _('Preliminary Complete Theme Review'),
    REVIEWED_XUL_THEME_UPDATE: _('Updated Complete Theme Review'),
    REVIEWED_ADDON_REVIEW: _('Moderated Add-on Review'),
    REVIEWED_ADDON_REVIEW_POORLY: _('Add-on Review Moderation Reverted'),
    REVIEWED_CONTENT_REVIEW: _('Add-on Content Review'),
    REVIEWED_EXTENSION_HIGHEST_RISK:
        _('Post-Approval Add-on Review (Highest Risk)'),
    REVIEWED_EXTENSION_HIGH_RISK:
        _('Post-Approval Add-on Review (High Risk)'),
    REVIEWED_EXTENSION_MEDIUM_RISK:
        _('Post-Approval Add-on Review (Medium Risk)'),
    REVIEWED_EXTENSION_LOW_RISK:
        _('Post-Approval Add-on Review (Low Risk)'),
}

REVIEWED_OVERDUE_BONUS = 2
REVIEWED_OVERDUE_LIMIT = 7

REVIEWED_SCORES = {
    REVIEWED_MANUAL: 0,
    REVIEWED_ADDON_FULL: 120,
    REVIEWED_ADDON_UPDATE: 80,
    REVIEWED_DICT_FULL: 60,
    REVIEWED_DICT_UPDATE: 60,
    REVIEWED_LP_FULL: 60,
    REVIEWED_LP_UPDATE: 60,
    REVIEWED_PERSONA: 5,
    REVIEWED_STATICTHEME: 5,
    REVIEWED_SEARCH_FULL: 30,
    REVIEWED_SEARCH_UPDATE: 30,
    REVIEWED_XUL_THEME_FULL: 80,
    REVIEWED_XUL_THEME_UPDATE: 80,
    REVIEWED_ADDON_REVIEW: 1,
    REVIEWED_ADDON_REVIEW_POORLY: -1,  # -REVIEWED_ADDON_REVIEW,
    REVIEWED_CONTENT_REVIEW: 10,
    REVIEWED_EXTENSION_HIGHEST_RISK: 140,
    REVIEWED_EXTENSION_HIGH_RISK: 120,
    REVIEWED_EXTENSION_MEDIUM_RISK: 90,
    REVIEWED_EXTENSION_LOW_RISK: 0,
}

REVIEWED_AMO = (
    REVIEWED_ADDON_FULL,
    REVIEWED_ADDON_UPDATE,
    REVIEWED_DICT_FULL,
    REVIEWED_DICT_UPDATE,
    REVIEWED_LP_FULL,
    REVIEWED_LP_UPDATE,
    REVIEWED_SEARCH_FULL,
    REVIEWED_SEARCH_UPDATE,
    REVIEWED_XUL_THEME_FULL,
    REVIEWED_XUL_THEME_UPDATE,
    REVIEWED_STATICTHEME,
    REVIEWED_ADDON_REVIEW,
    REVIEWED_CONTENT_REVIEW,
    REVIEWED_EXTENSION_HIGHEST_RISK,
    REVIEWED_EXTENSION_HIGH_RISK,
    REVIEWED_EXTENSION_MEDIUM_RISK,
    REVIEWED_EXTENSION_LOW_RISK,
)

REVIEWED_LEVELS = [
    {'name': _('Level 1'), 'points': 2160},
    {'name': _('Level 2'), 'points': 4320},
    {'name': _('Level 3'), 'points': 8700},
    {'name': _('Level 4'), 'points': 21000},
    {'name': _('Level 5'), 'points': 45000},
    {'name': _('Level 6'), 'points': 96000},
    {'name': _('Level 7'), 'points': 300000},
    {'name': _('Level 8'), 'points': 1200000},
    {'name': _('Level 9'), 'points': 3000000},
]

# Review queue pagination
REVIEWS_PER_PAGE = 200
REVIEWS_PER_PAGE_MAX = 400

# Theme review queue constants.
THEME_INITIAL_LOCKS = 5  # Initial number of themes to check out.
THEME_LOCK_EXPIRY = 30  # Minutes.

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
    ACTION_APPROVE: _('Approve')
}

THEME_REJECT_REASONS = {
    # 0: _('Other rejection reason'),
    1: _('Sexual or pornographic content'),
    2: _('Inappropriate or offensive content'),
    3: _('Violence, war, or weaponry images'),
    4: _('Nazi or other hate content'),
    5: _('Defamatory content'),
    6: _('Online gambling'),
    7: _('Spam content'),
    8: _('Low-quality, stretched, or blank image'),
    9: _('Header image alignment problem'),
}


WOULD_NOT_HAVE_BEEN_AUTO_APPROVED = 0
WOULD_HAVE_BEEN_AUTO_APPROVED = 1
AUTO_APPROVED = 2
NOT_AUTO_APPROVED = 3

AUTO_APPROVAL_VERDICT_CHOICES = (
    (WOULD_NOT_HAVE_BEEN_AUTO_APPROVED,
        'Would have been auto-approved (dry-run mode was in effect)'),
    (WOULD_HAVE_BEEN_AUTO_APPROVED,
        'Would *not* have been auto-approved (dry-run mode was in effect)'),
    (AUTO_APPROVED, 'Was auto-approved'),
    (NOT_AUTO_APPROVED, 'Was *not* auto-approved'),
)
