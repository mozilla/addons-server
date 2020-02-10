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
# Can review a static theme.
STATIC_THEMES_REVIEW = AclPermission('Addons', 'ThemeReview')
# Can review recommend(ed|able) add-ons
ADDONS_RECOMMENDED_REVIEW = AclPermission('Addons', 'RecommendedReview')

# Can edit all collections.
COLLECTIONS_EDIT = AclPermission('Collections', 'Edit')
# Can contribute to community managed collection: COLLECTION_FEATURED_THEMES_ID
COLLECTIONS_CONTRIBUTE = AclPermission('Collections', 'Contribute')

# Can view statistics for all addons, regardless of privacy settings.
STATS_VIEW = AclPermission('Stats', 'View')

# Can submit experiments.
EXPERIMENTS_SUBMIT = AclPermission('Experiments', 'submit')

# Can localize all locales.
LOCALIZER = AclPermission('Localizer', '%')

# Can edit user accounts.
USERS_EDIT = AclPermission('Users', 'Edit')

# Can moderate add-on ratings submitted by users.
RATINGS_MODERATE = AclPermission('Ratings', 'Moderate')

# Can access advanced reviewer features meant for admins, such as disabling an
# add-on or clearing needs admin review flags.
REVIEWS_ADMIN = AclPermission('Reviews', 'Admin')

# Can access advanced admin features, like deletion.
ADMIN_ADVANCED = AclPermission('Admin', 'Advanced')

# Can add/edit/delete DiscoveryItems.
DISCOVERY_EDIT = AclPermission('Discovery', 'Edit')

# Can list/access abuse reports
ABUSEREPORTS_EDIT = AclPermission('AbuseReports', 'Edit')

# Can submit language packs. #11788 and #11793
LANGPACK_SUBMIT = AclPermission('LanguagePack', 'Submit')

# Can access the scanners results admin.
ADMIN_SCANNERS_RESULTS_VIEW = AclPermission('Admin', 'ScannersResultsView')
# Can use "actions" on the scanners results.
ADMIN_SCANNERS_RESULTS_EDIT = AclPermission('Admin', 'ScannersResultsEdit')
# Can access the scanners rules admin.
ADMIN_SCANNERS_RULES_VIEW = AclPermission('Admin', 'ScannersRulesView')
# Can edit the scanners rules.
ADMIN_SCANNERS_RULES_EDIT = AclPermission('Admin', 'ScannersRulesEdit')
# Can edit things in the scanners query admin (code search).
ADMIN_SCANNERS_QUERY_EDIT = AclPermission('Admin', 'ScannersQueryEdit')
# Can view things the scanners query admin (code search).
ADMIN_SCANNERS_QUERY_VIEW = AclPermission('Admin', 'ScannersQueryView')

# Can create/edit a Block in the blocklist - the change may require signoff
BLOCKLIST_CREATE = AclPermission('Blocklist', 'Create')
# Can signoff a Block creation/edit submission
BLOCKLIST_SIGNOFF = AclPermission('Blocklist', 'Signoff')

# All permissions, for easy introspection
PERMISSIONS_LIST = [
    x for x in vars().values() if isinstance(x, AclPermission)]

# Mapping between django-style object permissions and our own. By default,
# require superuser admins (which also have all other permissions anyway) to do
# something, and then add some custom ones.
DJANGO_PERMISSIONS_MAPPING = defaultdict(lambda: SUPERPOWERS)

DJANGO_PERMISSIONS_MAPPING.update({
    'abuse.change_abusereport': ABUSEREPORTS_EDIT,
    'abuse.delete_abusereport': ADMIN_ADVANCED,
    # Note that ActivityLog's ModelAdmin actually forbids deletion entirely.
    # This is just here to allow deletion of users, because django checks
    # foreign keys even though users are only soft-deleted and related objects
    # will be kept.
    'activity.delete_activitylog': ADMIN_ADVANCED,
    'addons.change_addon': ADDONS_EDIT,
    'addons.add_addonuser': ADMIN_ADVANCED,
    'addons.change_addonuser': ADMIN_ADVANCED,
    'addons.delete_addonuser': ADMIN_ADVANCED,
    # Users with Admin:Curation can do anything to ReplacementAddon.
    # In addition, the modeladmin will also check for Addons:Edit and give them
    # read-only access to the changelist (obj=None passed to the
    # has_change_permission() method)
    'addons.change_replacementaddon': ADMIN_CURATION,
    'addons.add_replacementaddon': ADMIN_CURATION,
    'addons.delete_replacementaddon': ADMIN_CURATION,

    'bandwagon.change_collection': COLLECTIONS_EDIT,
    'bandwagon.delete_collection': ADMIN_ADVANCED,

    'blocklist.add_block': BLOCKLIST_CREATE,
    'blocklist.change_block': BLOCKLIST_CREATE,
    'blocklist.delete_block': BLOCKLIST_CREATE,
    'blocklist.view_block': REVIEWS_ADMIN,
    'blocklist.add_blocksubmission': BLOCKLIST_CREATE,
    'blocklist.change_blocksubmission': BLOCKLIST_CREATE,
    'blocklist.signoff_blocksubmission': BLOCKLIST_SIGNOFF,
    'blocklist.view_blocksubmission': REVIEWS_ADMIN,

    'discovery.add_discoveryitem': DISCOVERY_EDIT,
    'discovery.change_discoveryitem': DISCOVERY_EDIT,
    'discovery.delete_discoveryitem': DISCOVERY_EDIT,
    'discovery.add_secondaryheroshelf': DISCOVERY_EDIT,
    'discovery.change_secondaryheroshelf': DISCOVERY_EDIT,
    'discovery.delete_secondaryheroshelf': DISCOVERY_EDIT,

    'files.change_file': ADMIN_ADVANCED,

    'hero.add_primaryhero': DISCOVERY_EDIT,
    'hero.change_primaryhero': DISCOVERY_EDIT,
    'hero.delete_primaryhero': DISCOVERY_EDIT,
    'hero.add_secondaryheromodule': DISCOVERY_EDIT,
    'hero.change_secondaryheromodule': DISCOVERY_EDIT,
    'hero.delete_secondaryheromodule': DISCOVERY_EDIT,

    'reviewers.delete_reviewerscore': ADMIN_ADVANCED,

    'scanners.add_scannerrule': ADMIN_SCANNERS_RULES_EDIT,
    'scanners.change_scannerrule': ADMIN_SCANNERS_RULES_EDIT,
    'scanners.delete_scannerrule': ADMIN_SCANNERS_RULES_EDIT,
    'scanners.view_scannerrule': ADMIN_SCANNERS_RULES_VIEW,
    'scanners.view_scannerresult': ADMIN_SCANNERS_RESULTS_VIEW,

    'scanners.add_scannerqueryrule': ADMIN_SCANNERS_QUERY_EDIT,
    'scanners.change_scannerqueryrule': ADMIN_SCANNERS_QUERY_EDIT,
    'scanners.delete_scannerqueryrule': ADMIN_SCANNERS_QUERY_EDIT,
    'scanners.change_scannerqueryresult': ADMIN_SCANNERS_QUERY_EDIT,
    'scanners.view_scannerqueryrule': ADMIN_SCANNERS_QUERY_VIEW,
    'scanners.view_scannerqueryresult': ADMIN_SCANNERS_QUERY_VIEW,

    'users.change_userprofile': USERS_EDIT,
    'users.delete_userprofile': ADMIN_ADVANCED,

    'users.add_disposableemaildomainrestriction,': ADMIN_ADVANCED,
    'users.add_emailuserrestriction': ADMIN_ADVANCED,
    'users.add_ipnetworkuserrestriction': ADMIN_ADVANCED,
    'users.change_disposableemaildomainrestriction,': ADMIN_ADVANCED,
    'users.change_emailuserrestriction': ADMIN_ADVANCED,
    'users.change_ipnetworkuserrestriction': ADMIN_ADVANCED,
    'users.delete_disposableemaildomainrestriction,': ADMIN_ADVANCED,
    'users.delete_emailuserrestriction': ADMIN_ADVANCED,
    'users.delete_ipnetworkuserrestriction': ADMIN_ADVANCED,

    'ratings.change_rating': RATINGS_MODERATE,
    'ratings.delete_rating': ADMIN_ADVANCED,

    'versions.change_version': ADMIN_ADVANCED,
})
