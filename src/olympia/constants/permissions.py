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

# Can bypass all API throttles on the site. User used by releng scripts have
# this, as well as some QA on dev/stage.
API_BYPASS_THROTTLING = AclPermission('API', 'BypassThrottling')

# Can modify editorial content on the site.
ADMIN_CURATION = AclPermission('Admin', 'Curation')
# Can edit the properties of any add-on (pseduo-admin).
ADDONS_EDIT = AclPermission('Addons', 'Edit')
# Can view deleted add-ons in the API.
ADDONS_VIEW_DELETED = AclPermission('Addons', 'ViewDeleted')
# Can view only the reviewer tools.
REVIEWER_TOOLS_VIEW = AclPermission('ReviewerTools', 'View')
# Can view only the reviewer tools.
REVIEWER_TOOLS_UNLISTED_VIEW = AclPermission('ReviewerTools', 'ViewUnlisted')

# These users gain access to the accounts API to super-create users.
ACCOUNTS_SUPER_CREATE = AclPermission('Accounts', 'SuperCreate')

# Can review a listed add-on.
ADDONS_REVIEW = AclPermission('Addons', 'Review')
# Can review an unlisted add-on.
ADDONS_REVIEW_UNLISTED = AclPermission('Addons', 'ReviewUnlisted')
# Can submit a content review for a listed add-on.
ADDONS_CONTENT_REVIEW = AclPermission('Addons', 'ContentReview')
# Can edit the message of the day in the reviewer tools.
ADDON_REVIEWER_MOTD_EDIT = AclPermission('AddonReviewerMOTD', 'Edit')
# Can review a static theme.
STATIC_THEMES_REVIEW = AclPermission('Addons', 'ThemeReview')
# Can review recommend(ed|able) add-ons
ADDONS_RECOMMENDED_REVIEW = AclPermission('Addons', 'RecommendedReview')
# Can triage (and therefore see in the queues) add-ons with a temporary delay
ADDONS_TRIAGE_DELAYED = AclPermission('Addons', 'TriageDelayed')
# Can see add-ons with all due dates in the queue, rather than just upcoming ones
ADDONS_ALL_DUE_DATES = AclPermission('Addons', 'AllDueDates')
# Can view/make choices in 2nd level approval queue
ADDONS_HIGH_IMPACT_APPROVE = AclPermission('Addons', 'HighImpactApprove')

# Can download developer provided source code files
ADDONS_SOURCE_DOWNLOAD = AclPermission('Addons', 'SourceDownload')

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
# Or delete ratings.
RATINGS_DELETE = AclPermission('Ratings', 'Delete')

# Can access advanced reviewer features meant for admins, such as disabling an
# add-on or clearing needs admin review flags.
REVIEWS_ADMIN = AclPermission('Reviews', 'Admin')

# Can access advanced admin features, like deletion.
ADMIN_ADVANCED = AclPermission('Admin', 'Advanced')

# Can add/edit/delete DiscoveryItems.
DISCOVERY_EDIT = AclPermission('Discovery', 'Edit')

# Can list/access abuse reports
ABUSEREPORTS_EDIT = AclPermission('AbuseReports', 'Edit')

# Can view Cinder policies and sync them from django admin.
CINDER_POLICIES_VIEW = AclPermission('CinderPolicies', 'View')

# Can submit language packs. #11788 and #11793
LANGPACK_SUBMIT = AclPermission('LanguagePack', 'Submit')

# Can submit add-ons signed with Mozilla internal certificate, or add-ons with
# a guid ending with reserved suffixes like @mozilla.com
SYSTEM_ADDON_SUBMIT = AclPermission('SystemAddon', 'Submit')

# Can automatically bypass trademark checks
TRADEMARK_BYPASS = AclPermission('Trademark', 'Bypass')

# Can create AppVersion instances
APPVERSIONS_CREATE = AclPermission('AppVersions', 'Create')

# Can view/edit usage tiers
ADMIN_USAGE_TIER_EDIT = AclPermission('Admin', 'UsageTierEdit')
ADMIN_USAGE_TIER_VIEW = AclPermission('Admin', 'UsageTierView')

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

# Can create/edit regional restrictions for add-ons
ADMIN_REGIONALRESTRICTIONS = AclPermission('Admin', 'RegionalRestrictionsEdit')

# Can view/edit rating denied words
ADMIN_RATING_DENIED_WORD_EDIT = AclPermission('Admin', 'RatingDeniedWordEdit')
ADMIN_RATING_DENIED_WORD_VIEW = AclPermission('Admin', 'RatingDeniedWordView')

# Cnan view/edit disposable email domain restrictions
ADMIN_DISPOSABLE_EMAIL_EDIT = AclPermission('Admin', 'DisposableEmailEdit')
ADMIN_DISPOSABLE_EMAIL_VIEW = AclPermission('Admin', 'DisposableEmailView')

# Can edit/view Django Waffle Flags/Samples/Switches
WAFFLE_VIEW = AclPermission('Admin', 'WaffleView')
WAFFLE_EDIT = AclPermission('Admin', 'WaffleEdit')

# Can view/edit site configuration in django admin.
ADMIN_CONFIG_VIEW = AclPermission('Admin', 'ConfigView')
ADMIN_CONFIG_EDIT = AclPermission('Admin', 'ConfigEdit')


def _addchangedelete(app, model, permission):
    """Helper to expand an "edit" permission to add/change/delete."""
    return {f'{app}.{perm}_{model}': permission for perm in ('add', 'change', 'delete')}


# All permissions, for easy introspection
PERMISSIONS_LIST = [x for x in vars().values() if isinstance(x, AclPermission)]

# Mapping between django-style object permissions and our own. By default,
# require superuser admins (which also have all other permissions anyway) to do
# something, and then add some custom ones.
DJANGO_PERMISSIONS_MAPPING = defaultdict(lambda: SUPERPOWERS)

DJANGO_PERMISSIONS_MAPPING.update(
    {
        'abuse.change_abusereport': ABUSEREPORTS_EDIT,
        'abuse.view_cinderpolicy': CINDER_POLICIES_VIEW,
        'addons.change_addon': ADDONS_EDIT,
        **_addchangedelete('addons', 'addonuser', ADMIN_ADVANCED),
        'addons.change_addonreviewerflags': ADMIN_ADVANCED,
        'addons.view_replacementaddon': ADDONS_EDIT,
        **_addchangedelete(
            'addons', 'addonregionalrestrictions', ADMIN_REGIONALRESTRICTIONS
        ),
        # Users with Admin:Curation can do anything to AddonBrowserMapping.
        **_addchangedelete('addons', 'addonbrowsermapping', ADMIN_CURATION),
        'bandwagon.change_collection': COLLECTIONS_EDIT,
        'bandwagon.delete_collection': ADMIN_ADVANCED,
        **_addchangedelete('blocklist', 'block', BLOCKLIST_CREATE),
        'blocklist.view_block': REVIEWS_ADMIN,
        'blocklist.add_blocklistsubmission': BLOCKLIST_CREATE,
        'blocklist.change_blocklistsubmission': BLOCKLIST_CREATE,
        'blocklist.signoff_blocklistsubmission': BLOCKLIST_SIGNOFF,
        'blocklist.view_blocklistsubmission': REVIEWS_ADMIN,
        **_addchangedelete('discovery', 'discoveryaddon', DISCOVERY_EDIT),
        **_addchangedelete('discovery', 'discoveryitem', DISCOVERY_EDIT),
        'discovery.view_discoverypromotedgroup': DISCOVERY_EDIT,
        **_addchangedelete('discovery', 'homepageshelves', DISCOVERY_EDIT),
        **_addchangedelete('discovery', 'primaryheroimageupload', DISCOVERY_EDIT),
        **_addchangedelete('discovery', 'secondaryheroshelf', DISCOVERY_EDIT),
        'files.change_file': ADMIN_ADVANCED,
        'files.view_webextpermission': ADMIN_ADVANCED,
        'files.view_filevalidation': ADMIN_ADVANCED,
        'files.view_filemanifest': ADMIN_ADVANCED,
        **_addchangedelete('promoted', 'promotedaddon', DISCOVERY_EDIT),
        **_addchangedelete('hero', 'primaryhero', DISCOVERY_EDIT),
        **_addchangedelete('hero', 'secondaryheromodule', DISCOVERY_EDIT),
        'promoted.delete_promotedapproval': DISCOVERY_EDIT,
        'promoted.view_promotedapproval': DISCOVERY_EDIT,
        **_addchangedelete(
            'ratings', 'deniedratingword', ADMIN_RATING_DENIED_WORD_EDIT
        ),
        'ratings.view_deniedratingword': ADMIN_RATING_DENIED_WORD_VIEW,
        'ratings.view_rating': RATINGS_MODERATE,
        'ratings.delete_rating': RATINGS_DELETE,
        **_addchangedelete('reviewers', 'needshumanreview', ADMIN_ADVANCED),
        **_addchangedelete('reviewers', 'usagetier', ADMIN_USAGE_TIER_EDIT),
        'reviewers.view_usagetier': ADMIN_USAGE_TIER_VIEW,
        **_addchangedelete('scanners', 'scannerrule', ADMIN_SCANNERS_RULES_EDIT),
        'scanners.view_scannerrule': ADMIN_SCANNERS_RULES_VIEW,
        'scanners.view_scannerresult': ADMIN_SCANNERS_RESULTS_VIEW,
        **_addchangedelete('scanners', 'scannerqueryrule', ADMIN_SCANNERS_QUERY_EDIT),
        'scanners.change_scannerqueryresult': ADMIN_SCANNERS_QUERY_EDIT,
        'scanners.delete_scannerqueryresult': ADMIN_SCANNERS_QUERY_EDIT,
        'scanners.view_scannerqueryrule': ADMIN_SCANNERS_QUERY_VIEW,
        'scanners.view_scannerqueryresult': ADMIN_SCANNERS_QUERY_VIEW,
        **_addchangedelete('tags', 'tag', DISCOVERY_EDIT),
        'users.change_userprofile': USERS_EDIT,
        **_addchangedelete(
            'users', 'disposableemaildomainrestriction', ADMIN_DISPOSABLE_EMAIL_EDIT
        ),
        'users.view_disposableemaildomainrestriction': ADMIN_DISPOSABLE_EMAIL_VIEW,
        **_addchangedelete('users', 'emailuserrestriction', ADMIN_ADVANCED),
        **_addchangedelete('users', 'ipnetworkuserrestriction', ADMIN_ADVANCED),
        'users.view_userrestrictionhistory': ADMIN_ADVANCED,
        'users.view_userhistory': ADMIN_ADVANCED,
        'users.change_bannedusercontent': ADMIN_ADVANCED,
        'versions.change_version': ADMIN_ADVANCED,
        'versions.change_versionreviewerflags': ADMIN_ADVANCED,
        'versions.view_versionprovenance': ADMIN_ADVANCED,
        **_addchangedelete('waffle', 'flag', WAFFLE_EDIT),
        **_addchangedelete('waffle', 'sample', WAFFLE_EDIT),
        **_addchangedelete('waffle', 'switch', WAFFLE_EDIT),
        'waffle.view_flag': WAFFLE_VIEW,
        'waffle.view_sample': WAFFLE_VIEW,
        'waffle.view_switch': WAFFLE_VIEW,
        **_addchangedelete('zadmin', 'config', ADMIN_CONFIG_EDIT),
        'zadmin.view_config': ADMIN_CONFIG_VIEW,
    }
)
