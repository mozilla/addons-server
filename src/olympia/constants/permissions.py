from collections import defaultdict, namedtuple


AclPermission = namedtuple('AclPermission', 'app, action')

# Null rule.  Only useful in tests really as no access group should have this.
NONE = AclPermission('None', 'None')

# A special wildcard permission to use when checking if someone has access to
# any admin, or if an admin is accessible by someone with any Admin:<something>
# permission.
ANY_ADMIN = AclPermission('Admin', '%')

# Another special permission, that only few (2-3) admins have. This grants
# access to anything.
SUPERPOWERS = AclPermission('*', '*')

# Can access admin-specific tools.
ADMIN_TOOLS = AclPermission('Admin', 'Tools')
# Can modify editorial content on the site.
ADMIN_CURATION = AclPermission('Admin', 'Curation')
# Can edit the properties of any add-on (pseduo-admin).
ADDONS_EDIT = AclPermission('Addons', 'Edit')
# Can configure some settings of an add-on.
ADDONS_CONFIGURE = AclPermission('Addons', 'Configure')
# Can view deleted add-ons in the API.
ADDONS_VIEW_DELETED = AclPermission('Addons', 'ViewDeleted')
# Can view only the reviewer tools.
REVIEWER_TOOLS_VIEW = AclPermission('ReviewerTools', 'View')

# These users gain access to the accounts API to super-create users.
ACCOUNTS_SUPER_CREATE = AclPermission('Accounts', 'SuperCreate')

# Can review a listed add-on.
ADDONS_REVIEW = AclPermission('Addons', 'Review')
# Can review an unlisted add-on.
ADDONS_REVIEW_UNLISTED = AclPermission('Addons', 'ReviewUnlisted')
# Can access add-ons post-review information.
ADDONS_POST_REVIEW = AclPermission('Addons', 'PostReview')
# Can submit a content review for a listed add-on.
ADDONS_CONTENT_REVIEW = AclPermission('Addons', 'ContentReview')
# Can edit the message of the day in the reviewer tools.
ADDON_REVIEWER_MOTD_EDIT = AclPermission('AddonReviewerMOTD', 'Edit')
# Can review a background theme (persona).
THEMES_REVIEW = AclPermission('Personas', 'Review')
# Can review a static theme.
STATIC_THEMES_REVIEW = AclPermission('Addons', 'ThemeReview')

# Can edit all collections.
COLLECTIONS_EDIT = AclPermission('Collections', 'Edit')
# Can contribute to community managed collection: COLLECTION_FEATURED_THEMES_ID
COLLECTIONS_CONTRIBUTE = AclPermission('Collections', 'Contribute')

# Can view statistics for all addons, regardless of privacy settings.
STATS_VIEW = AclPermission('Stats', 'View')
# Can view collection statistics.
COLLECTION_STATS_VIEW = AclPermission('CollectionStats', 'View')

# Can submit experiments.
EXPERIMENTS_SUBMIT = AclPermission('Experiments', 'submit')

# Can localize all locales.
LOCALIZER = AclPermission('Localizer', '%')

# Can edit user accounts.
USERS_EDIT = AclPermission('Users', 'Edit')

# Can access mailing list.
MAILING_LISTS_VIEW = AclPermission('MailingLists', 'View')

# Can moderate add-on ratings submitted by users.
RATINGS_MODERATE = AclPermission('Ratings', 'Moderate')

# Can access advanced reviewer features meant for admins, such as disabling an
# add-on or clearing needs admin review flags.
REVIEWS_ADMIN = AclPermission('Reviews', 'Admin')

# All permissions, for easy introspection
PERMISSIONS_LIST = [
    x for x in vars().values() if isinstance(x, AclPermission)]

# Mapping between django-style object permissions and our own. By default,
# require superuser admins (which also have all other permissions anyway) to do
# something, and then add some custom ones.
DJANGO_PERMISSIONS_MAPPING = defaultdict(lambda: SUPERPOWERS)
# Curators can do anything to ReplacementAddon. In addition, the modeladmin
# will also check for addons:edit and give them read-only access to the
# changelist (obj=None passed to the has_change_permission() method)
DJANGO_PERMISSIONS_MAPPING.update({
    'addons.change_replacementaddon': ADMIN_CURATION,
    'addons.add_replacementaddon': ADMIN_CURATION,
    'addons.delete_replacementaddon': ADMIN_CURATION,

    'users.change_userprofile': USERS_EDIT,

    'ratings.change_rating': RATINGS_MODERATE,
})
