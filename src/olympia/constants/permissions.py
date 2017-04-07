from collections import namedtuple


AclPermission = namedtuple('AclPermission', 'app, action')

# Special null rule.
NONE = AclPermission('None', 'None')

# Admin super powers.  Very few users will have this permission (2-3)
ADMIN = AclPermission('Admin', '%')

# Can view admin tools.
ADMINTOOLS = AclPermission('AdminTools', 'View')
# Can view add-on reviewer admin tools.
REVIEWERADMINTOOLS = AclPermission('ReviewerAdminTools', 'View')
# Can view theme reviewer admin tools.
THEMEADMINTOOLS = AclPermission('SeniorPersonasTools', 'View')
# Can edit the properties of any add-on (pseduo-admin).
ADDONS_EDIT = AclPermission('Addons', 'Edit')
# Can configure some settings of an add-on.
ADDONS_CONFIGURE = AclPermission('Addons', 'Configure')
# Can view only the reviewer (editor) tools.
REVIEWERTOOLS = AclPermission('ReviewerTools', 'View')

# These users gain access to the accounts API to super-create users.
ACCOUNTS_SUPERCREATE = AclPermission('Accounts', 'SuperCreate')

# Can submit an editor review for a listed add-on.
ADDONS_REVIEW = AclPermission('Addons', 'Review')
# Can submit an editor review for an unlisted add-on.
ADDONS_REVIEWUNLISTED = AclPermission('Addons', 'ReviewUnlisted')
# Can access add-ons post-review information.
ADDONS_POST_REVIEW = AclPermission('Addons', 'PostReview')
# Can edit the message of the day in the reviewer tools.
ADDONREVIEWERMOTD_EDIT = AclPermission('AddonReviewerMOTD', 'Edit')
# Can submit an editor review for a background theme (persona).
THEMES_REVIEW = AclPermission('Personas', 'Review')

# Can edit all collections.
COLLECTIONS_EDIT = AclPermission('Collections', 'Edit')

# Can view statistics for all addons, regardless of privacy settings.
STATS = AclPermission('Stats', 'View')
# Can view collection statistics.
COLLECTIONSTATS = AclPermission('CollectionStats', 'View')
# Can view revenue statistics.
REVENUESTATS = AclPermission('RevenueStats', 'View')

# Can submit experiments.
EXPERIMENTS_SUBMIT = AclPermission('Experiments', 'submit')

# Can localize all locales.
LOCALIZER = AclPermission('Localizer', '%')

# Can edit user accounts:
USERS_EDIT = AclPermission('Users', 'Edit')

# Can access mailing list
MAILINGLISTS = AclPermission('MailingLists', 'View')
