import re

from django.utils.translation import ugettext_lazy as _


# Add-on and File statuses.
STATUS_NULL = 0  # No review type chosen yet, add-on is incomplete.
STATUS_AWAITING_REVIEW = 1  # File waiting for review.
STATUS_PENDING = 2  # Personas (lightweight themes) waiting for review.
STATUS_NOMINATED = 3  # Waiting for review.
STATUS_PUBLIC = 4  # Approved.
STATUS_DISABLED = 5  # Rejected (single files) or disabled by Mozilla (addons).
_STATUS_LISTED = 6  # Deprecated. See bug 616242
STATUS_BETA = 7  # Beta file, only available on approved add-ons.
_STATUS_LITE = 8  # Deprecated, preliminary reviewed.
_STATUS_LITE_AND_NOMINATED = 9  # Deprecated, prelim & waiting for full review.
STATUS_DELETED = 11  # Add-on has been deleted.
STATUS_REJECTED = 12  # This applies only to rejected personas.
STATUS_REVIEW_PENDING = 14  # Themes queue, reviewed, needs further action.

STATUS_CHOICES_ADDON = {
    STATUS_NULL: _(u'Incomplete'),
    STATUS_NOMINATED: _(u'Awaiting Review'),
    STATUS_PUBLIC: _(u'Approved'),
    STATUS_DISABLED: _(u'Disabled by Mozilla'),
    STATUS_DELETED: _(u'Deleted'),
}

STATUS_CHOICES_PERSONA = {
    STATUS_NULL: STATUS_CHOICES_ADDON[STATUS_NULL],
    STATUS_PENDING: _(u'Pending approval'),
    STATUS_PUBLIC: STATUS_CHOICES_ADDON[STATUS_PUBLIC],
    STATUS_DISABLED: STATUS_CHOICES_ADDON[STATUS_DISABLED],
    STATUS_DELETED: STATUS_CHOICES_ADDON[STATUS_DELETED],
    STATUS_REJECTED: _(u'Rejected'),
    # Approved, but the developer would like to put it public when they want.
    STATUS_REVIEW_PENDING: _(u'Flagged for further review'),
}

STATUS_CHOICES_FILE = {
    STATUS_AWAITING_REVIEW: _(u'Awaiting Review'),
    STATUS_PUBLIC: _(u'Approved'),
    STATUS_DISABLED: _(u'Disabled by Mozilla'),
    STATUS_BETA: _(u'Beta'),
}

# We need to expose nice values that aren't localisable.
STATUS_CHOICES_API = {
    STATUS_NULL: 'incomplete',
    STATUS_AWAITING_REVIEW: 'unreviewed',
    STATUS_PENDING: 'pending',
    STATUS_NOMINATED: 'nominated',
    STATUS_PUBLIC: 'public',
    STATUS_DISABLED: 'disabled',
    STATUS_BETA: 'beta',
    STATUS_DELETED: 'deleted',
    STATUS_REJECTED: 'rejected',
    STATUS_REVIEW_PENDING: 'review-pending',
}

STATUS_CHOICES_API_LOOKUP = {
    'incomplete': STATUS_NULL,
    'unreviewed': STATUS_AWAITING_REVIEW,
    'pending': STATUS_PENDING,
    'nominated': STATUS_NOMINATED,
    'public': STATUS_PUBLIC,
    'disabled': STATUS_DISABLED,
    'beta': STATUS_BETA,
    'deleted': STATUS_DELETED,
    'rejected': STATUS_REJECTED,
    'review-pending': STATUS_REVIEW_PENDING,
}

REVIEWED_STATUSES = (STATUS_PUBLIC,)
UNREVIEWED_ADDON_STATUSES = (STATUS_NOMINATED,)
UNREVIEWED_FILE_STATUSES = (STATUS_AWAITING_REVIEW, STATUS_PENDING)
VALID_ADDON_STATUSES = (STATUS_NOMINATED, STATUS_PUBLIC)
VALID_FILE_STATUSES = (STATUS_AWAITING_REVIEW, STATUS_PUBLIC, STATUS_BETA)

# Version channels
RELEASE_CHANNEL_UNLISTED = 1
RELEASE_CHANNEL_LISTED = 2

RELEASE_CHANNEL_CHOICES = (
    (RELEASE_CHANNEL_UNLISTED, _(u'Unlisted')),
    (RELEASE_CHANNEL_LISTED, _(u'Listed')),
)

CHANNEL_CHOICES_API = {
    RELEASE_CHANNEL_UNLISTED: 'unlisted',
    RELEASE_CHANNEL_LISTED: 'listed',
}

CHANNEL_CHOICES_LOOKUP = {
    'unlisted': RELEASE_CHANNEL_UNLISTED,
    'listed': RELEASE_CHANNEL_LISTED,
}

# Add-on author roles.
AUTHOR_ROLE_VIEWER = 1
AUTHOR_ROLE_DEV = 4
AUTHOR_ROLE_OWNER = 5
AUTHOR_ROLE_SUPPORT = 6

AUTHOR_CHOICES = (
    (AUTHOR_ROLE_OWNER, _(u'Owner')),
    (AUTHOR_ROLE_DEV, _(u'Developer')),
    (AUTHOR_ROLE_VIEWER, _(u'Viewer')),
    (AUTHOR_ROLE_SUPPORT, _(u'Support')),
)

# Addon types
ADDON_ANY = 0
ADDON_EXTENSION = 1
ADDON_THEME = 2
ADDON_DICT = 3
ADDON_SEARCH = 4
ADDON_LPAPP = 5
ADDON_LPADDON = 6
ADDON_PLUGIN = 7
ADDON_API = 8  # not actually a type but used to identify extensions + themes
ADDON_PERSONA = 9

# Addon type groupings.
GROUP_TYPE_ADDON = [ADDON_EXTENSION, ADDON_DICT, ADDON_SEARCH, ADDON_LPAPP,
                    ADDON_LPADDON, ADDON_PLUGIN, ADDON_API]
GROUP_TYPE_THEME = [ADDON_THEME, ADDON_PERSONA]

# Singular
ADDON_TYPE = {
    ADDON_EXTENSION: _(u'Extension'),
    ADDON_THEME: _(u'Complete Theme'),
    ADDON_DICT: _(u'Dictionary'),
    ADDON_SEARCH: _(u'Search Engine'),
    ADDON_LPAPP: _(u'Language Pack (Application)'),
    ADDON_LPADDON: _(u'Language Pack (Add-on)'),
    ADDON_PLUGIN: _(u'Plugin'),
    ADDON_PERSONA: _(u'Theme'),
}

# Plural
ADDON_TYPES = {
    ADDON_EXTENSION: _(u'Extensions'),
    ADDON_THEME: _(u'Complete Themes'),
    ADDON_DICT: _(u'Dictionaries'),
    ADDON_SEARCH: _(u'Search Tools'),
    ADDON_LPAPP: _(u'Language Packs (Application)'),
    ADDON_LPADDON: _(u'Language Packs (Add-on)'),
    ADDON_PLUGIN: _(u'Plugins'),
    ADDON_PERSONA: _(u'Themes'),
}

# Searchable Add-on Types
ADDON_SEARCH_TYPES = [
    ADDON_ANY,
    ADDON_EXTENSION,
    ADDON_THEME,
    ADDON_DICT,
    ADDON_SEARCH,
    ADDON_LPAPP,
    ADDON_PERSONA,
]

# Icons
ADDON_ICONS = {
    ADDON_ANY: 'default-addon.png',
    ADDON_THEME: 'default-theme.png',
}

# We use these slugs in browse page urls.
ADDON_SLUGS = {
    ADDON_EXTENSION: 'extensions',
    ADDON_THEME: 'themes',
    ADDON_DICT: 'language-tools',
    ADDON_LPAPP: 'language-tools',
    ADDON_PERSONA: 'personas',
    ADDON_SEARCH: 'search-tools',
}

# These are used in the update API.
ADDON_SLUGS_UPDATE = {
    ADDON_EXTENSION: 'extension',
    ADDON_THEME: 'theme',
    ADDON_DICT: 'extension',
    ADDON_SEARCH: 'search',
    ADDON_LPAPP: 'item',
    ADDON_LPADDON: 'extension',
    ADDON_PERSONA: 'background-theme',
    ADDON_PLUGIN: 'plugin',
}

# A slug to ID map for the search API. Included are all ADDON_TYPES that are
# found in ADDON_SEARCH_TYPES.
ADDON_SEARCH_SLUGS = {
    'any': ADDON_ANY,
    'extension': ADDON_EXTENSION,
    'theme': ADDON_THEME,
    'dictionary': ADDON_DICT,
    'search': ADDON_SEARCH,
    'language': ADDON_LPAPP,
    'persona': ADDON_PERSONA,
}

ADDON_TYPE_CHOICES_API = {
    ADDON_EXTENSION: 'extension',
    ADDON_THEME: 'theme',
    ADDON_DICT: 'dictionary',
    ADDON_SEARCH: 'search',
    ADDON_LPAPP: 'language',
    ADDON_PERSONA: 'persona',
}

# Edit addon information
MAX_TAGS = 20
MIN_TAG_LENGTH = 2
MAX_CATEGORIES = 2
VALID_CONTRIBUTION_DOMAINS = ('paypal.me', 'patreon.com', 'micropayment.de')

# Icon upload sizes
ADDON_ICON_SIZES = [32, 48, 64, 128, 256, 512]

# Preview upload sizes [thumb, full]
ADDON_PREVIEW_SIZES = [(200, 150), (700, 525)]

# Persona image sizes [preview, full]
PERSONA_IMAGE_SIZES = {
    'header': [(680, 100), (3000, 200)],
    'footer': [None, (3000, 100)],
    'icon': [None, (32, 32)],
}

# Accepted image MIME-types
IMG_TYPES = ('image/png', 'image/jpeg', 'image/jpg')
VIDEO_TYPES = ('video/webm',)

# These types don't maintain app compatibility in the db.  Instead, we look at
# APP.types and APP_TYPE_SUPPORT to figure out where they are compatible.
NO_COMPAT = (ADDON_SEARCH, ADDON_DICT, ADDON_PERSONA)
HAS_COMPAT = {t: t not in NO_COMPAT for t in ADDON_TYPES}

# Contributions
CONTRIB_NONE = 0
CONTRIB_PASSIVE = 1
CONTRIB_AFTER = 2
CONTRIB_ROADBLOCK = 3

CONTRIB_CHOICES = (
    (CONTRIB_PASSIVE,
     _(u"Only ask on this add-on's page and developer profile")),
    (CONTRIB_AFTER, _(u"Ask after users start downloading this add-on")),
    (CONTRIB_ROADBLOCK, _(u"Ask before users can download this add-on")),
)

# Personas
PERSONAS_ADDON_ID = 10900  # Add-on ID of the Personas Plus Add-on
PERSONAS_FIREFOX_MIN = '3.6'  # First Firefox version to support Personas
PERSONAS_THUNDERBIRD_MIN = '3.1'  # Ditto for Thunderbird

# Collections.
COLLECTION_NORMAL = 0
COLLECTION_SYNCHRONIZED = 1
COLLECTION_FEATURED = 2
COLLECTION_RECOMMENDED = 3
COLLECTION_FAVORITES = 4
COLLECTION_MOBILE = 5
COLLECTION_ANONYMOUS = 6

COLLECTIONS_NO_CONTRIB = (COLLECTION_SYNCHRONIZED, COLLECTION_FAVORITES)

COLLECTION_SPECIAL_SLUGS = {
    COLLECTION_MOBILE: 'mobile',
    COLLECTION_FAVORITES: 'favorites',
}

COLLECTION_CHOICES = {
    COLLECTION_NORMAL: 'Normal',
    COLLECTION_SYNCHRONIZED: 'Synchronized',
    COLLECTION_FEATURED: 'Featured',
    COLLECTION_RECOMMENDED: 'Generated Recommendations',
    COLLECTION_FAVORITES: 'Favorites',
    COLLECTION_MOBILE: 'Mobile',
    COLLECTION_ANONYMOUS: 'Anonymous',
}

COLLECTION_SEARCH_CHOICES = [
    COLLECTION_NORMAL,
    COLLECTION_FEATURED,
    COLLECTION_RECOMMENDED,
    COLLECTION_MOBILE,
    COLLECTION_ANONYMOUS,
]

# Validation.

# A skeleton set of passing validation results.
# TODO: Move to validator, generate dynamically via ErrorBundle instance.
VALIDATOR_SKELETON_RESULTS = {
    "errors": 0,
    "warnings": 0,
    "notices": 0,
    "success": True,
    "compatibility_summary": {"notices": 0, "errors": 0, "warnings": 0},
    "metadata": {"requires_chrome": False, "listed": True},
    "messages": [],
    "message_tree": {},
    "detected_type": "extension",
    "ending_tier": 5,
}

# A skeleton set of validation results for a system error.
VALIDATOR_SKELETON_EXCEPTION = {
    "errors": 1,
    "warnings": 0,
    "notices": 0,
    "success": True,
    "compatibility_summary": {"notices": 0, "errors": 0, "warnings": 0},
    "metadata": {"requires_chrome": False, "listed": True},
    "messages": [
        {"id": ["validator", "unexpected_exception"],
         "message": "Sorry, we couldn't load your add-on.",
         "description": [
            "Validation was unable to complete successfully due to an "
            "unexpected error.",
            "The error has been logged, but please consider filing an issue "
            "report here: http://bit.ly/1POrYYU"],
         "type": "error",
         "tier": 1,
         "for_appversions": None,
         "uid": "35432f419340461897aa8362398339c4"}
    ],
    "message_tree": {},
    "detected_type": "extension",
    "ending_tier": 5,
}

VALIDATOR_SKELETON_EXCEPTION_WEBEXT = {
    "errors": 1,
    "warnings": 0,
    "notices": 0,
    "success": True,
    "compatibility_summary": {"notices": 0, "errors": 0, "warnings": 0},
    "metadata": {
        "requires_chrome": False,
        "listed": True,
        "is_webextension": True
    },
    "messages": [
        {"id": ["validator", "unexpected_exception"],
         "message": "Sorry, we couldn't load your WebExtension.",
         "description": [
            "Validation was unable to complete successfully due to an "
            "unexpected error.",
            "Check https://developer.mozilla.org/en-US/Add-ons/WebExtensions "
            "to ensure your webextension is valid or file a bug at "
            "http://bit.ly/1POrYYU"],
         "type": "error",
         "tier": 1,
         "for_appversions": None,
         "uid": "35432f419340461897aa8362398339c4"}
    ],
    "message_tree": {},
    "detected_type": "extension",
    "ending_tier": 5,
}

# Contributions.
FOUNDATION_ORG = 1  # The charities.id of the Mozilla Foundation.

VERSION_BETA = re.compile(r"""(a|alpha|b|beta|pre|rc) # Either of these
                              (([\.-]\d)?\d*)         # followed by nothing
                              $                       # or 123 or .123 or -123
                              """, re.VERBOSE)
VERSION_SEARCH = re.compile('\.(\d+)$')

# Reviewer Tools
EDITOR_VIEWING_INTERVAL = 8  # How often we ping for "who's watching?"
EDITOR_REVIEW_LOCK_LIMIT = 3  # How many pages can an editor "watch"

# Types of SiteEvent
SITE_EVENT_OTHER = 1
SITE_EVENT_EXCEPTION = 2
SITE_EVENT_RELEASE = 3
SITE_EVENT_CHANGE = 4

SITE_EVENT_CHOICES = {
    SITE_EVENT_OTHER: _('Other'),
    SITE_EVENT_EXCEPTION: _('Exception'),
    SITE_EVENT_RELEASE: _('Release'),
    SITE_EVENT_CHANGE: _('Change'),
}

# Types of Canned Responses for reviewer tools.
CANNED_RESPONSE_ADDON = 1
CANNED_RESPONSE_APP = 2  # Unused, should be removed
CANNED_RESPONSE_PERSONA = 3

CANNED_RESPONSE_CHOICES = {
    CANNED_RESPONSE_ADDON: _('Add-on'),
    CANNED_RESPONSE_APP: _('App'),
    CANNED_RESPONSE_PERSONA: _('Persona'),
}

# For use in urls.
ADDON_ID = r"""(?P<addon_id>[^/<>"']+)"""
ADDON_UUID = r'(?P<uuid>[\w]{8}-[\w]{4}-[\w]{4}-[\w]{4}-[\w]{12})'

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
REVIEWED_OVERDUE_BONUS = 2
REVIEWED_OVERDUE_LIMIT = 7
REVIEWED_PERSONA = 40
# TODO: Leaving room for persona points based on queue.
REVIEWED_SEARCH_FULL = 50
_REVIEWED_SEARCH_PRELIM = 51  # Deprecated for new reviews - no more prelim.
REVIEWED_SEARCH_UPDATE = 52
REVIEWED_THEME_FULL = 60
_REVIEWED_THEME_PRELIM = 61  # Deprecated for new reviews - no more prelim.
REVIEWED_THEME_UPDATE = 62
REVIEWED_ADDON_REVIEW = 80
REVIEWED_ADDON_REVIEW_POORLY = 81

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
    REVIEWED_OVERDUE_BONUS: _('Bonus for overdue reviews'),
    REVIEWED_OVERDUE_LIMIT: _('Days Before Bonus Points Applied'),
    REVIEWED_PERSONA: _('Theme Review'),
    REVIEWED_SEARCH_FULL: _('New Search Provider Review'),
    _REVIEWED_SEARCH_PRELIM: _('Preliminary Search Provider Review'),
    REVIEWED_SEARCH_UPDATE: _('Updated Search Provider Review'),
    REVIEWED_THEME_FULL: _('New Complete Theme Review'),
    _REVIEWED_THEME_PRELIM: _('Preliminary Complete Theme Review'),
    REVIEWED_THEME_UPDATE: _('Updated Complete Theme Review'),
    REVIEWED_ADDON_REVIEW: _('Moderated Add-on Review'),
    REVIEWED_ADDON_REVIEW_POORLY: _('Add-on Review Moderation Reverted'),
}

REVIEWED_SCORES = {
    REVIEWED_MANUAL: 0,
    REVIEWED_ADDON_FULL: 120,
    REVIEWED_ADDON_UPDATE: 80,
    REVIEWED_DICT_FULL: 60,
    REVIEWED_DICT_UPDATE: 60,
    REVIEWED_LP_FULL: 60,
    REVIEWED_LP_UPDATE: 60,
    REVIEWED_OVERDUE_BONUS: 2,
    REVIEWED_OVERDUE_LIMIT: 7,
    REVIEWED_PERSONA: 5,
    REVIEWED_SEARCH_FULL: 30,
    REVIEWED_SEARCH_UPDATE: 30,
    REVIEWED_THEME_FULL: 80,
    REVIEWED_THEME_UPDATE: 80,
    REVIEWED_ADDON_REVIEW: 1,
    REVIEWED_ADDON_REVIEW_POORLY: -1,  # -REVIEWED_ADDON_REVIEW
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
    REVIEWED_THEME_FULL,
    REVIEWED_THEME_UPDATE,
    REVIEWED_ADDON_REVIEW,
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

# Amount of hours to hide add-on reviews from users with permission
# Addons:DelayedReviews
REVIEW_LIMITED_DELAY_HOURS = 20

# Default strict_min_version and strict_max_version for WebExtensions
DEFAULT_WEBEXT_MIN_VERSION = '42.0'
DEFAULT_WEBEXT_MAX_VERSION = '*'

# Android only started to support WebExtensions with version 48
DEFAULT_WEBEXT_MIN_VERSION_ANDROID = '48.0'

# The default version of Firefox that supports WebExtensions without an id
DEFAULT_WEBEXT_MIN_VERSION_NO_ID = '48.0'

E10S_UNKNOWN = 0
E10S_COMPATIBLE = 1
E10S_COMPATIBLE_WEBEXTENSION = 2
E10S_INCOMPATIBLE = 3

E10S_COMPATIBILITY_CHOICES = (
    (E10S_UNKNOWN, _('Unknown')),
    # We don't need to show developers the actual, more granular state, only
    # that it's compatible or not.
    (E10S_COMPATIBLE_WEBEXTENSION, _('Compatible')),
    (E10S_COMPATIBLE, _('Compatible')),
    (E10S_INCOMPATIBLE, _('Incompatible')),
)

E10S_COMPATIBILITY_CHOICES_API = {
    E10S_UNKNOWN: 'unknown',
    E10S_COMPATIBLE_WEBEXTENSION: 'compatible-webextension',
    E10S_COMPATIBLE: 'compatible',
    E10S_INCOMPATIBLE: 'incompatible',
}

ADDON_GUID_PATTERN = re.compile(
    # Match {uuid} or something@host.tld ("something" being optional)
    # guids. Copied from mozilla-central XPIProvider.jsm.
    r'^(\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}'
    r'|[a-z0-9-\._]*\@[a-z0-9-\._]+)$', re.IGNORECASE)
