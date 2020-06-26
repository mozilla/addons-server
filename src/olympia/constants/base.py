import re
from collections import namedtuple

from django.utils.translation import ugettext_lazy as _


# Add-on and File statuses.
STATUS_NULL = 0  # No review type chosen yet, add-on is incomplete.
STATUS_AWAITING_REVIEW = 1  # File waiting for review.
_STATUS_PENDING = 2  # Deprecated. Was Personas waiting for review.
STATUS_NOMINATED = 3  # Waiting for review.
STATUS_APPROVED = 4  # Approved.
STATUS_DISABLED = 5  # Rejected (single files) or disabled by Mozilla (addons).
_STATUS_LISTED = 6  # Deprecated. See bug 616242
_STATUS_BETA = 7  # Deprecated, see addons-server/issues/7163
_STATUS_LITE = 8  # Deprecated, preliminary reviewed.
_STATUS_LITE_AND_NOMINATED = 9  # Deprecated, prelim & waiting for full review.
STATUS_DELETED = 11  # Add-on has been deleted.
_STATUS_REJECTED = 12  # Deprecated. Applied only to rejected personas.
_STATUS_REVIEW_PENDING = 14  # Deprecated. Was personas, needing further action

STATUS_CHOICES_ADDON = {
    STATUS_NULL: _(u'Incomplete'),
    STATUS_NOMINATED: _(u'Awaiting Review'),
    STATUS_APPROVED: _(u'Approved'),
    STATUS_DISABLED: _(u'Disabled by Mozilla'),
    STATUS_DELETED: _(u'Deleted'),
}

STATUS_CHOICES_FILE = {
    STATUS_AWAITING_REVIEW: _(u'Awaiting Review'),
    STATUS_APPROVED: _(u'Approved'),
    STATUS_DISABLED: _(u'Disabled by Mozilla'),
}

# We need to expose nice values that aren't localisable.
STATUS_CHOICES_API = {
    STATUS_NULL: 'incomplete',
    STATUS_AWAITING_REVIEW: 'unreviewed',
    STATUS_NOMINATED: 'nominated',
    STATUS_APPROVED: 'public',
    STATUS_DISABLED: 'disabled',
    STATUS_DELETED: 'deleted',
}

STATUS_CHOICES_API_LOOKUP = {
    'incomplete': STATUS_NULL,
    'unreviewed': STATUS_AWAITING_REVIEW,
    'nominated': STATUS_NOMINATED,
    'public': STATUS_APPROVED,
    'disabled': STATUS_DISABLED,
    'deleted': STATUS_DELETED,
}

REVIEWED_STATUSES = (STATUS_APPROVED,)
UNREVIEWED_ADDON_STATUSES = (STATUS_NOMINATED,)
UNREVIEWED_FILE_STATUSES = (STATUS_AWAITING_REVIEW,)
VALID_ADDON_STATUSES = (STATUS_NOMINATED, STATUS_APPROVED)
VALID_FILE_STATUSES = (STATUS_AWAITING_REVIEW, STATUS_APPROVED)

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

UPLOAD_SOURCE_DEVHUB = 1
UPLOAD_SOURCE_API = 2
UPLOAD_SOURCE_CHOICES = (
    (UPLOAD_SOURCE_DEVHUB, _('Developer Hub')),
    (UPLOAD_SOURCE_API, _('API')),
)

# Add-on author roles.
AUTHOR_ROLE_DEV = 4
AUTHOR_ROLE_OWNER = 5
AUTHOR_ROLE_DELETED = 6

AUTHOR_CHOICES = (
    (AUTHOR_ROLE_OWNER, _('Owner')),
    (AUTHOR_ROLE_DEV, _('Developer')),
    (AUTHOR_ROLE_DELETED, _('(Deleted)')),
)

# Addon types
ADDON_ANY = 0
ADDON_EXTENSION = 1
_ADDON_THEME = 2
ADDON_DICT = 3
ADDON_SEARCH = 4
ADDON_LPAPP = 5
ADDON_LPADDON = 6
ADDON_PLUGIN = 7
ADDON_API = 8  # not actually a type but used to identify extensions + themes
_ADDON_PERSONA = 9  # Deprecated.  Aka Lightweight Themes.
ADDON_STATICTHEME = 10
_ADDON_WEBAPP = 11  # Deprecated.  Marketplace cruft.

# Addon type groupings.
GROUP_TYPE_ADDON = [ADDON_EXTENSION, ADDON_DICT, ADDON_SEARCH, ADDON_LPAPP,
                    ADDON_LPADDON, ADDON_PLUGIN, ADDON_API]
GROUP_TYPE_THEME = [ADDON_STATICTHEME]

# Singular
ADDON_TYPE = {
    ADDON_EXTENSION: _(u'Extension'),
    _ADDON_THEME: _(u'Deprecated Complete Theme'),
    ADDON_DICT: _(u'Dictionary'),
    ADDON_SEARCH: _(u'Search Engine'),
    ADDON_LPAPP: _(u'Language Pack (Application)'),
    ADDON_LPADDON: _(u'Language Pack (Add-on)'),
    ADDON_PLUGIN: _(u'Plugin'),
    _ADDON_PERSONA: _(u'Deprecated LWT'),
    ADDON_STATICTHEME: _(u'Theme (Static)'),
}

# Plural
ADDON_TYPES = {
    ADDON_EXTENSION: _(u'Extensions'),
    _ADDON_THEME: _(u'Deprecated Complete Themes'),
    ADDON_DICT: _(u'Dictionaries'),
    ADDON_SEARCH: _(u'Search Tools'),
    ADDON_LPAPP: _(u'Language Packs (Application)'),
    ADDON_LPADDON: _(u'Language Packs (Add-on)'),
    ADDON_PLUGIN: _(u'Plugins'),
    _ADDON_PERSONA: _(u'Deprecated LWTs'),
    ADDON_STATICTHEME: _(u'Themes (Static)'),
}

# Searchable Add-on Types
ADDON_SEARCH_TYPES = [
    ADDON_ANY,
    ADDON_EXTENSION,
    _ADDON_THEME,
    ADDON_DICT,
    ADDON_SEARCH,
    ADDON_LPAPP,
    _ADDON_PERSONA,
    ADDON_STATICTHEME,
]

# We use these slugs in browse page urls.
ADDON_SLUGS = {
    ADDON_EXTENSION: 'extensions',
    ADDON_DICT: 'language-tools',
    ADDON_LPAPP: 'language-tools',
    ADDON_SEARCH: 'search-tools',
    ADDON_STATICTHEME: 'themes',
}

# These are used in the update API.
ADDON_SLUGS_UPDATE = {
    ADDON_EXTENSION: 'extension',
    _ADDON_THEME: 'theme',
    ADDON_DICT: 'extension',
    ADDON_SEARCH: 'search',
    ADDON_LPAPP: 'item',
    ADDON_LPADDON: 'extension',
    _ADDON_PERSONA: 'background-theme',
    ADDON_PLUGIN: 'plugin',
    ADDON_STATICTHEME: 'static-theme',
}

# A slug to ID map for the search API. Included are all ADDON_TYPES that are
# found in ADDON_SEARCH_TYPES.
ADDON_SEARCH_SLUGS = {
    'any': ADDON_ANY,
    'extension': ADDON_EXTENSION,
    'theme': _ADDON_THEME,
    'dictionary': ADDON_DICT,
    'search': ADDON_SEARCH,
    'language': ADDON_LPAPP,
    'persona': _ADDON_PERSONA,
    'statictheme': ADDON_STATICTHEME,
}

ADDON_TYPE_CHOICES_API = {
    ADDON_EXTENSION: 'extension',
    _ADDON_THEME: 'theme',
    ADDON_DICT: 'dictionary',
    ADDON_SEARCH: 'search',
    ADDON_LPAPP: 'language',
    _ADDON_PERSONA: 'persona',
    ADDON_STATICTHEME: 'statictheme',
}

ADDON_TYPES_WITH_STATS = [ADDON_EXTENSION, ADDON_STATICTHEME]

# Edit addon information
MAX_TAGS = 20
MIN_TAG_LENGTH = 2
MAX_CATEGORIES = 2
CONTRIBUTE_UTM_PARAMS = {
    'utm_content': 'product-page-contribute',
    'utm_medium': 'referral',
    'utm_source': 'addons.mozilla.org'}
VALID_CONTRIBUTION_DOMAINS = (
    'buymeacoffee.com',
    'donate.mozilla.org',
    'flattr.com',
    'ko-fi.com',
    'liberapay.com',
    'micropayment.de',
    'opencollective.com',
    'patreon.com',
    'paypal.com',
    'paypal.me'
)

# Icon upload sizes
ADDON_ICON_SIZES = [32, 64, 128]

_size_tuple = namedtuple('SizeTuple', 'width height')
# Preview upload sizes - see mozilla/addons-server#9487 for background.
ADDON_PREVIEW_SIZES = {
    'thumb': _size_tuple(640, 480),
    'min': _size_tuple(1000, 750),
    'full': _size_tuple(2400, 1800)
}

# Static theme preview sizes
THEME_PREVIEW_SIZES = {
    'header': {
        'thumbnail': _size_tuple(473, 64),
        'full': _size_tuple(680, 92),
        'position': 0},
    'list': {
        'thumbnail': _size_tuple(529, 64),
        'full': _size_tuple(760, 92),
        'position': 1},
    # single is planned to be the new default size in 2019 Q1.
    'single': {
        'thumbnail': _size_tuple(501, 64),
        'full': _size_tuple(720, 92),
        'position': 2},
}
THEME_FRAME_COLOR_DEFAULT = 'rgba(229,230,232,1)'
THEME_PREVIEW_TOOLBAR_HEIGHT = 92  # The template toolbar is this height.

# Accepted image extensions and MIME-types
THEME_BACKGROUND_EXTS = ('.jpg', '.jpeg', '.png', '.apng', '.svg', '.gif')
IMG_TYPES = ('image/png', 'image/jpeg')
VIDEO_TYPES = ('video/webm',)

# The string concatinating all accepted image MIME-types with '|'
SUPPORTED_IMAGE_TYPES = '|'.join(IMG_TYPES)

# Acceptable Add-on file extensions.
# This is being used by `parse_addon` so please make sure we don't have
# to touch add-ons before removing anything from this list.
VALID_ADDON_FILE_EXTENSIONS = ('.crx', '.xpi', '.xml', '.zip')

# These types don't maintain app compatibility in the db.  Instead, we look at
# APP.types and APP_TYPE_SUPPORT to figure out where they are compatible.
NO_COMPAT = (ADDON_SEARCH, ADDON_DICT)
HAS_COMPAT = {t: t not in NO_COMPAT for t in ADDON_TYPES}

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
VALIDATOR_SKELETON_RESULTS = {
    "errors": 0,
    "warnings": 0,
    "notices": 0,
    "success": True,
    "compatibility_summary": {"notices": 0, "errors": 0, "warnings": 0},
    "metadata": {
        "listed": True,
    },
    "messages": [],
    "message_tree": {},
    "ending_tier": 5,
}

# A skeleton set of validation results for a system error.
VALIDATOR_SKELETON_EXCEPTION_WEBEXT = {
    "errors": 1,
    "warnings": 0,
    "notices": 0,
    "success": False,
    "compatibility_summary": {"notices": 0, "errors": 0, "warnings": 0},
    "metadata": {
        "listed": True,
        "is_webextension": True,
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
         "fatal": True,
         "tier": 1,
         "for_appversions": None,
         "uid": "35432f419340461897aa8362398339c4"}
    ],
    "message_tree": {},
    "ending_tier": 5,
}

VERSION_SEARCH = re.compile(r'\.(\d+)$')

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

# The default version of Firefox that supported `browser_specific_settings`
DEFAULT_WEBEXT_MIN_VERSION_BROWSER_SPECIFIC = '48.0'

# The version of desktop Firefox that first supported static themes.
DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX = '53.0'

# The version of Android that first minimally supported static themes.
DEFAULT_STATIC_THEME_MIN_VERSION_ANDROID = '65.0'

# The version of Firefox that first supported webext dictionaries. Note that
# on AMO at the moment, dicts have no compatibility exposed - ADDON_DICT is in
# NO_COMPAT. But this allows the compat information to be saved to the database
# to change our mind later.
# Dicts are not compatible with Firefox for Android, only desktop is relevant.
DEFAULT_WEBEXT_DICT_MIN_VERSION_FIREFOX = '61.0'

ADDON_GUID_PATTERN = re.compile(
    # Match {uuid} or something@host.tld ("something" being optional)
    # guids. Copied from mozilla-central XPIProvider.jsm.
    r'^(\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}'
    r'|[a-z0-9-\._]*\@[a-z0-9-\._]+)$', re.IGNORECASE)

SYSTEM_ADDON_GUIDS = (
    '@mozilla.com',
    '@mozilla.org',
    '@pioneer.mozilla.org',
    '@search.mozilla.org',
    '@shield.mozilla.org'
)

MOZILLA_TRADEMARK_SYMBOLS = (
    'mozilla', 'firefox')

ALLOWED_TRADEMARK_SUBMITTING_EMAILS = (
    '@mozilla.com', '@mozilla.org')

# If you add/remove any sources, update the docs: /api/download_sources.html
# Note there are some additional sources here for historical/backwards compat.
DOWNLOAD_SOURCES_FULL = (
    'addondetail', 'addon-detail-version', 'api', 'category', 'collection',
    'creatured', 'developers', 'discovery-dependencies', 'discovery-upsell',
    'discovery-video', 'email', 'find-replacement', 'fxcustomization',
    'fxfirstrun', 'fxwhatsnew', 'homepagebrowse', 'homepagepromo',
    'installservice', 'mostshared', 'oftenusedwith', 'prerelease-banner',
    'recommended', 'rockyourfirefox', 'search', 'sharingapi',
    'similarcollections', 'ss', 'userprofile', 'version-history',

    'co-hc-sidebar', 'co-dp-sidebar',

    'cb-hc-featured', 'cb-dl-featured', 'cb-hc-toprated', 'cb-dl-toprated',
    'cb-hc-mostpopular', 'cb-dl-mostpopular', 'cb-hc-recentlyadded',
    'cb-dl-recentlyadded',

    'hp-btn-promo', 'hp-dl-promo', 'hp-hc-featured', 'hp-dl-featured',
    'hp-hc-upandcoming', 'hp-dl-upandcoming', 'hp-hc-mostpopular',
    'hp-dl-mostpopular', 'hp-contest-winners',

    'dp-hc-oftenusedwith', 'dp-dl-oftenusedwith', 'dp-hc-othersby',
    'dp-dl-othersby', 'dp-btn-primary', 'dp-btn-version', 'dp-btn-devchannel',
    'dp-hc-dependencies', 'dp-dl-dependencies', 'dp-hc-upsell', 'dp-dl-upsell',
)

DOWNLOAD_SOURCES_PREFIX = (
    'external-', 'mozcom-', 'discovery-', 'cb-btn-', 'cb-dl-')
