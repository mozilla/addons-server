from django_jinja import library

from olympia.amo.urlresolvers import reverse


@library.global_function
def admin_site_links():
    return {
        'addons': [
            ('Search for add-ons by name or id',
             reverse('zadmin.addon-search')),
            ('Featured add-ons', reverse('zadmin.features')),
            ('Discovery Pane promo modules',
             reverse('discovery.module_admin')),
            ('Monthly Pick', reverse('zadmin.monthly_pick')),
            ('Fake mail', reverse('zadmin.mail')),
            ('ACR Reports', reverse('zadmin.compat')),
            ('Email Add-on Developers', reverse('zadmin.email_devs')),
            ('Replacement Addons', reverse(
                'admin:addons_replacementaddon_changelist')),
        ],
        'users': [
            ('Configure groups', reverse('admin:access_group_changelist')),
        ],
        'settings': [
            ('View site settings', reverse('zadmin.settings')),
            ('View request environment', reverse('zadmin.env')),
            ('Django admin pages', reverse('zadmin.home')),
            ('Site Events', reverse('zadmin.site_events')),
        ],
        'tools': [
            ('Manage elasticsearch', reverse('zadmin.elastic')),
            ('Purge data from memcache', reverse('zadmin.memcache')),
            ('View event log', reverse('admin:reviewers_eventlog_changelist')),
            ('View addon log',
             reverse('admin:activity_activitylog_changelist')),
        ],
    }
