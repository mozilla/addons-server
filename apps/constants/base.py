from datetime import datetime
import re

from tower import ugettext_lazy as _


# Add-on and File statuses.
STATUS_NULL = 0
STATUS_UNREVIEWED = 1
STATUS_PENDING = 2
STATUS_NOMINATED = 3
STATUS_PUBLIC = 4
STATUS_DISABLED = 5
STATUS_LISTED = 6
STATUS_BETA = 7
STATUS_LITE = 8
STATUS_LITE_AND_NOMINATED = 9
STATUS_PURGATORY = 10  # A temporary home; bug 614686
STATUS_DELETED = 11
STATUS_REJECTED = 12  # This applies only to apps (for now)
STATUS_PUBLIC_WAITING = 13  # bug 740967
STATUS_REVIEW_PENDING = 14  # Themes queue, reviewed, needs further action.

STATUS_CHOICES = {
    STATUS_NULL: _(u'Incomplete'),
    STATUS_UNREVIEWED: _(u'Awaiting Preliminary Review'),
    STATUS_PENDING: _(u'Pending approval'),
    STATUS_NOMINATED: _(u'Awaiting Full Review'),
    STATUS_PUBLIC: _(u'Fully Reviewed'),
    STATUS_DISABLED: _(u'Disabled by Mozilla'),
    STATUS_LISTED: _(u'Listed'),
    STATUS_BETA: _(u'Beta'),
    STATUS_LITE: _(u'Preliminarily Reviewed'),
    STATUS_LITE_AND_NOMINATED:
        _(u'Preliminarily Reviewed and Awaiting Full Review'),
    STATUS_PURGATORY: _(u'Pending a review choice'),
    STATUS_DELETED: _(u'Deleted'),
    STATUS_REJECTED: _(u'Rejected'),
    # Approved, but the developer would like to put it public when they want.
    # The need to go to the marketplace and actualy make it public.
    STATUS_PUBLIC_WAITING: _('Approved but waiting'),
}

# We need to expose nice values that aren't localisable.
STATUS_CHOICES_API = {
    STATUS_NULL: 'incomplete',
    STATUS_UNREVIEWED: 'unreviewed',
    STATUS_PENDING: 'pending',
    STATUS_NOMINATED: 'nominated',
    STATUS_PUBLIC: 'public',
    STATUS_DISABLED: 'disabled',
    STATUS_LISTED: 'listed',
    STATUS_BETA: 'beta',
    STATUS_LITE: 'lite',
    STATUS_LITE_AND_NOMINATED: 'lite-nominated',
    STATUS_PURGATORY: 'purgatory',
    STATUS_DELETED: 'deleted',
    STATUS_REJECTED: 'rejected',
    STATUS_PUBLIC_WAITING: 'waiting',
}

STATUS_CHOICES_API_LOOKUP = {
    'incomplete': STATUS_NULL,
    'unreviewed': STATUS_UNREVIEWED,
    'pending': STATUS_PENDING,
    'nominated': STATUS_NOMINATED,
    'public': STATUS_PUBLIC,
    'disabled': STATUS_DISABLED,
    'listed': STATUS_LISTED,
    'beta': STATUS_BETA,
    'lite': STATUS_LITE,
    'lite-nominated': STATUS_LITE_AND_NOMINATED,
    'purgatory': STATUS_PURGATORY,
    'deleted': STATUS_DELETED,
    'rejected': STATUS_REJECTED,
    'waiting': STATUS_PUBLIC_WAITING,
}

PUBLIC_IMMEDIATELY = None
# Our MySQL does not store microseconds.
PUBLIC_WAIT = datetime.max.replace(microsecond=0)

REVIEWED_STATUSES = (STATUS_LITE, STATUS_LITE_AND_NOMINATED, STATUS_PUBLIC)
UNREVIEWED_STATUSES = (STATUS_UNREVIEWED, STATUS_PENDING, STATUS_NOMINATED,
                       STATUS_PURGATORY)
VALID_STATUSES = (STATUS_UNREVIEWED, STATUS_PENDING, STATUS_NOMINATED,
                  STATUS_PUBLIC, STATUS_LISTED, STATUS_BETA, STATUS_LITE,
                  STATUS_LITE_AND_NOMINATED, STATUS_PURGATORY,
                  STATUS_PUBLIC_WAITING)
# We don't show addons/versions with UNREVIEWED_STATUS in public.
LISTED_STATUSES = tuple(st for st in VALID_STATUSES
                        if st not in (STATUS_PENDING, STATUS_PUBLIC_WAITING))

# An add-on in one of these statuses is awaiting a review.
STATUS_UNDER_REVIEW = (STATUS_UNREVIEWED, STATUS_NOMINATED,
                       STATUS_LITE_AND_NOMINATED)

LITE_STATUSES = (STATUS_LITE, STATUS_LITE_AND_NOMINATED)

MIRROR_STATUSES = (STATUS_PUBLIC, STATUS_BETA,
                   STATUS_LITE, STATUS_LITE_AND_NOMINATED)

# An add-on in one of these statuses can become premium.
PREMIUM_STATUSES = (STATUS_NULL,) + STATUS_UNDER_REVIEW

# Newly submitted apps begin life at this status.
WEBAPPS_UNREVIEWED_STATUS = STATUS_PENDING

# An app with this status makes its detail page "invisible".
WEBAPPS_UNLISTED_STATUSES = (STATUS_DISABLED, STATUS_PENDING,
                             STATUS_PUBLIC_WAITING, STATUS_REJECTED)

# The only statuses we use in the marketplace.
MARKET_STATUSES = (STATUS_NULL, STATUS_PENDING, STATUS_PUBLIC, STATUS_DISABLED,
                   STATUS_DELETED, STATUS_REJECTED, STATUS_PUBLIC_WAITING)

# Types of administrative review queues for an add-on:
ADMIN_REVIEW_FULL = 1
ADMIN_REVIEW_PRELIM = 2

ADMIN_REVIEW_TYPES = {
    ADMIN_REVIEW_FULL: _(u'Full'),
    ADMIN_REVIEW_PRELIM: _(u'Preliminary'),
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
ADDON_WEBAPP = 11  # Calling this ADDON_* is gross but we've gotta ship code.

# Singular
ADDON_TYPE = {
    ADDON_ANY: _(u'Any'),
    ADDON_EXTENSION: _(u'Extension'),
    ADDON_THEME: _(u'Theme'),
    ADDON_DICT: _(u'Dictionary'),
    ADDON_SEARCH: _(u'Search Engine'),
    ADDON_PLUGIN: _(u'Plugin'),
    ADDON_LPAPP: _(u'Language Pack (Application)'),
    ADDON_PERSONA: _(u'Persona'),
    ADDON_WEBAPP: _(u'App'),
}

# Plural
ADDON_TYPES = {
    ADDON_ANY: _(u'Any'),
    ADDON_EXTENSION: _(u'Extensions'),
    ADDON_THEME: _(u'Themes'),
    ADDON_DICT: _(u'Dictionaries'),
    ADDON_SEARCH: _(u'Search Tools'),
    ADDON_PLUGIN: _(u'Plugins'),
    ADDON_LPAPP: _(u'Language Packs (Application)'),
    ADDON_PERSONA: _(u'Personas'),
    ADDON_WEBAPP: _(u'Apps'),
}

# Searchable Add-on Types
ADDON_SEARCH_TYPES = [
    ADDON_ANY,
    ADDON_EXTENSION,
    ADDON_THEME,
    ADDON_DICT,
    ADDON_SEARCH,
    ADDON_LPAPP,
]

MARKETPLACE_TYPES = [ADDON_PERSONA, ADDON_WEBAPP]

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
    ADDON_WEBAPP: 'apps',
}

# These are used in the update API.
ADDON_SLUGS_UPDATE = {
    ADDON_EXTENSION: 'extension',
    ADDON_THEME: 'theme',
    ADDON_DICT: 'extension',
    ADDON_SEARCH: 'search',
    ADDON_LPAPP: 'item',
    ADDON_LPADDON: 'extension',
    ADDON_PERSONA: 'persona',
    ADDON_PLUGIN: 'plugin',
    ADDON_WEBAPP: 'app',
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

ADDON_FREE = 0
ADDON_PREMIUM = 1
ADDON_PREMIUM_INAPP = 2
ADDON_FREE_INAPP = 3
# The addon will have payments, but they aren't using our payment system.
ADDON_OTHER_INAPP = 4

ADDON_PREMIUM_TYPES = {
    ADDON_FREE: _('Free'),
    ADDON_PREMIUM: _('Premium'),
    ADDON_PREMIUM_INAPP: _('Premium with in-app payments'),
    ADDON_FREE_INAPP: _('Free with in-app payments'),
    ADDON_OTHER_INAPP: _("I'll use my own system for in-app payments")
}

# Non-locale versions for the API.
ADDON_PREMIUM_API = {
    ADDON_FREE: 'free',
}

# Apps that require some sort of payment prior to installing.
ADDON_PREMIUMS = (ADDON_PREMIUM, ADDON_PREMIUM_INAPP)
# Apps that do *not* require a payment prior to installing.
ADDON_FREES = (ADDON_FREE, ADDON_FREE_INAPP, ADDON_OTHER_INAPP)
ADDON_INAPPS = (ADDON_PREMIUM_INAPP, ADDON_FREE_INAPP)
ADDON_BECOME_PREMIUM = (ADDON_EXTENSION, ADDON_THEME, ADDON_DICT,
                        ADDON_LPAPP, ADDON_WEBAPP)

# Edit addon information
MAX_TAGS = 20
MIN_TAG_LENGTH = 2
MAX_CATEGORIES = 2

# Icon upload sizes
ADDON_ICON_SIZES = [32, 48, 64, 128, 256, 512]

# Preview upload sizes [thumb, full]
ADDON_PREVIEW_SIZES = [(200, 150), (700, 525)]

# Persona image sizes [preview, full]
PERSONA_IMAGE_SIZES = {
    'header': [(680, 100), (3000, 200)],
    'footer': [None, (3000, 100)],
}

# Accepted image MIME-types
IMG_TYPES = ('image/png', 'image/jpeg', 'image/jpg')
VIDEO_TYPES = ('video/webm',)

# These types don't maintain app compatibility in the db.  Instead, we look at
# APP.types and APP_TYPE_SUPPORT to figure out where they are compatible.
NO_COMPAT = (ADDON_SEARCH, ADDON_PERSONA)
HAS_COMPAT = dict((t, t not in NO_COMPAT) for t in ADDON_TYPES)

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

COLLECTION_ROLE_PUBLISHER = 0
COLLECTION_ROLE_ADMIN = 1

COLLECTION_AUTHOR_CHOICES = {
    COLLECTION_ROLE_PUBLISHER: 'Publisher',
    COLLECTION_ROLE_ADMIN: 'Admin',
}

# Contributions.
FOUNDATION_ORG = 1  # The charities.id of the Mozilla Foundation.

VERSION_BETA = re.compile('(a|alpha|b|beta|pre|rc)\d*$')
VERSION_SEARCH = re.compile('\.(\d+)$')

# Editor Tools
EDITOR_VIEWING_INTERVAL = 8  # How often we ping for "who's watching?"

# Used to watermark addons install.rdf and update.
WATERMARK_KEY = 'purchaser'
WATERMARK_KEY_HASH = '%s-hash' % WATERMARK_KEY
WATERMARK_KEYS = (WATERMARK_KEY, WATERMARK_KEY_HASH)

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
CANNED_RESPONSE_APP = 2
CANNED_RESPONSE_PERSONA = 3

CANNED_RESPONSE_CHOICES = {
    CANNED_RESPONSE_ADDON: _('Add-on'),
    CANNED_RESPONSE_APP: _('App'),
    CANNED_RESPONSE_PERSONA: _('Persona'),
}

APP_SLUG = r"""(?P<app_slug>[^/<>"']+)"""

# Reviewer Incentive Scores.
# Note: Don't change these since they're used as keys in the database.
REVIEWED_MANUAL = 0
REVIEWED_ADDON_FULL = 1
REVIEWED_ADDON_PRELIM = 2
REVIEWED_ADDON_UPDATED = 3
REVIEWED_DICT = 4
REVIEWED_LP = 5
REVIEWED_PERSONA = 6
REVIEWED_SEARCH = 7
REVIEWED_THEME = 8
REVIEWED_WEBAPP = 9

REVIEWED_CHOICES = {
    REVIEWED_MANUAL: _('Manual Reviewer Points'),
    REVIEWED_ADDON_FULL: _('Full Add-on Review'),
    REVIEWED_ADDON_PRELIM: _('Preliminary Add-on Review'),
    REVIEWED_ADDON_UPDATED: _('Updated Add-on Review'),
    REVIEWED_DICT: _('Dictionary Review'),
    REVIEWED_LP: _('Language Pack Review'),
    REVIEWED_PERSONA: _('Persona Review'),
    REVIEWED_SEARCH: _('Search Provider Review'),
    REVIEWED_THEME: _('Theme Review'),
    REVIEWED_WEBAPP: _('App Review'),
}

REVIEWED_SCORES = {
    REVIEWED_MANUAL: 0,
    REVIEWED_ADDON_FULL: 120,
    REVIEWED_ADDON_PRELIM: 60,
    REVIEWED_ADDON_UPDATED: 80,
    REVIEWED_DICT: 30,
    REVIEWED_LP: 30,
    REVIEWED_PERSONA: 5,
    REVIEWED_SEARCH: 60,
    REVIEWED_THEME: 80,
    REVIEWED_WEBAPP: 60,
}

# Percentage of what developers earn after Marketplace's cut.
MKT_CUT = .70

# Login credential source
LOGIN_SOURCE_UNKNOWN = 0
LOGIN_SOURCE_BROWSERID = 1
