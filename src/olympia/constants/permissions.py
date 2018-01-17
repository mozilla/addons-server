from collections import namedtuple


AclPermission = namedtuple('AclPermission', 'app, action')

# Null rule.  Only useful in tests really as no access group should have this.
NONE = AclPermission('None', 'None')

# Admin super powers.  Very few users will have this permission (2-3)
ADMIN = AclPermission('Admin', '%')

# Can view admin tools.
ADMIN_TOOLS_VIEW = AclPermission('AdminTools', 'View')
# Can view add-on reviewer admin tools.
REVIEWER_ADMIN_TOOLS_VIEW = AclPermission('ReviewerAdminTools', 'View')
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

# Can edit all collections.
COLLECTIONS_EDIT = AclPermission('Collections', 'Edit')

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

# Can access advanced reviewer features.
REVIEWS_EDIT = AclPermission('Reviews', 'Edit')

# All permissions, for easy introspection
PERMISSIONS_LIST = [
    x for x in vars().values() if isinstance(x, AclPermission)]
