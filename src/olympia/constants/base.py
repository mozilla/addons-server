import re
from collections import namedtuple

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
AUTHOR_ROLE_DEV = 4
AUTHOR_ROLE_OWNER = 5

AUTHOR_CHOICES = (
    (AUTHOR_ROLE_OWNER, _(u'Owner')),
    (AUTHOR_ROLE_DEV, _(u'Developer')),
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
ADDON_STATICTHEME = 10

# Addon type groupings.
GROUP_TYPE_ADDON = [ADDON_EXTENSION, ADDON_DICT, ADDON_SEARCH, ADDON_LPAPP,
                    ADDON_LPADDON, ADDON_PLUGIN, ADDON_API]
GROUP_TYPE_THEME = [ADDON_THEME, ADDON_PERSONA, ADDON_STATICTHEME]

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
    ADDON_STATICTHEME: _(u'Theme (Static)'),
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
    ADDON_STATICTHEME: _(u'Themes (Static)'),
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
    ADDON_STATICTHEME,
]

# Icons
ADDON_ICONS = {
    ADDON_ANY: 'default-addon.png',
    ADDON_THEME: 'default-theme.png',
    ADDON_STATICTHEME: 'default-theme.png',
}

# We use these slugs in browse page urls.
ADDON_SLUGS = {
    ADDON_EXTENSION: 'extensions',
    ADDON_THEME: 'themes',
    ADDON_DICT: 'language-tools',
    ADDON_LPAPP: 'language-tools',
    ADDON_PERSONA: 'personas',
    ADDON_SEARCH: 'search-tools',
    ADDON_STATICTHEME: 'static-themes',
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
    ADDON_STATICTHEME: 'static-theme',
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
    'statictheme': ADDON_STATICTHEME,
}

ADDON_TYPE_CHOICES_API = {
    ADDON_EXTENSION: 'extension',
    ADDON_THEME: 'theme',
    ADDON_DICT: 'dictionary',
    ADDON_SEARCH: 'search',
    ADDON_LPAPP: 'language',
    ADDON_PERSONA: 'persona',
    ADDON_STATICTHEME: 'statictheme',
}

# Edit addon information
MAX_TAGS = 20
MIN_TAG_LENGTH = 2
MAX_CATEGORIES = 2
VALID_CONTRIBUTION_DOMAINS = (
    'donate.mozilla.org',
    'liberapay.com',
    'micropayment.de',
    'opencollective.com',
    'patreon.com',
    'paypal.com',
    'paypal.me'
)

# Icon upload sizes
ADDON_ICON_SIZES = [32, 48, 64, 128, 256, 512]

# Preview upload sizes [thumb, full]
ADDON_PREVIEW_SIZES = [(200, 150), (700, 525)]

THEME_PREVIEW_SIZE = namedtuple('SizeTuple', 'width height')(680, 100)

# Persona image sizes [preview, full]
PERSONA_IMAGE_SIZES = {
    'header': [(680, 100), (3000, 200)],
    'footer': [None, (3000, 100)],
    'icon': [None, (32, 32)],
}

# Accepted image MIME-types
IMG_TYPES = ('image/png', 'image/jpeg')
VIDEO_TYPES = ('video/webm',)

# The string concatinating all accepted image MIME-types with '|'
SUPPORTED_IMAGE_TYPES = '|'.join(IMG_TYPES)

# These types don't maintain app compatibility in the db.  Instead, we look at
# APP.types and APP_TYPE_SUPPORT to figure out where they are compatible.
NO_COMPAT = (ADDON_SEARCH, ADDON_DICT, ADDON_PERSONA)
HAS_COMPAT = {t: t not in NO_COMPAT for t in ADDON_TYPES}

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

VERSION_BETA = re.compile(r"""(a|alpha|b|beta|pre|rc) # Either of these
                              (([\.-]\d)?\d*)         # followed by nothing
                              $                       # or 123 or .123 or -123
                              """, re.VERBOSE)
VERSION_SEARCH = re.compile('\.(\d+)$')

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

# For use in urls.
ADDON_ID = r"""(?P<addon_id>[^/<>"']+)"""
ADDON_UUID = r'(?P<uuid>[\w]{8}-[\w]{4}-[\w]{4}-[\w]{4}-[\w]{12})'

# Default strict_min_version and strict_max_version for WebExtensions
DEFAULT_WEBEXT_MIN_VERSION = '42.0'
DEFAULT_WEBEXT_MAX_VERSION = '*'

# Android only started to support WebExtensions with version 48
DEFAULT_WEBEXT_MIN_VERSION_ANDROID = '48.0'

# The default version of Firefox that supports WebExtensions without an id
DEFAULT_WEBEXT_MIN_VERSION_NO_ID = '48.0'

# The version of Firefox that first supported static themes.  Not Android yet.
DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX = '53.0'

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

SYSTEM_ADDON_GUIDS = (
    u'@mozilla.org', u'@shield.mozilla.org', u'@pioneer.mozilla.org')

MOZILLA_TRADEMARK_SYMBOLS = (
    'mozilla', 'firefox')

ALLOWED_TRADEMARK_SUBMITTING_EMAILS = (
    '@mozilla.com', '@mozilla.org')

DISCO_API_ALLOWED_PARAMETERS = (
    'telemetry-client-id', 'lang', 'platform', 'branch', 'study', 'edition')
