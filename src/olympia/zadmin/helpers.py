from jingo import register

from olympia.amo.urlresolvers import reverse


@register.function
def admin_site_links():
    return {
        'addons': [
            ('Search for add-ons by name or id',
             reverse('zadmin.addon-search')),
            ('Featured add-ons', reverse('zadmin.features')),
            ('Discovery Pane promo modules',
             reverse('discovery.module_admin')),
            ('Monthly Pick', reverse('zadmin.monthly_pick')),
            ('Bulk add-on validation', reverse('zadmin.validation')),
            ('Fake mail', reverse('zadmin.mail')),
            ('ACR Reports', reverse('zadmin.compat')),
            ('Email Add-on Developers', reverse('zadmin.email_devs')),
        ],
        'users': [
            ('Configure groups', reverse('admin:access_group_changelist')),
        ],
        'settings': [
            ('View site settings', reverse('zadmin.settings')),
            ('Django admin pages', reverse('zadmin.home')),
            ('Site Events', reverse('zadmin.site_events')),
        ],
        'tools': [
            ('View request environment', reverse('amo.env')),
            ('Manage elasticsearch', reverse('zadmin.elastic')),
            ('Purge data from memcache', reverse('zadmin.memcache')),
            ('Purge pages from zeus', reverse('zadmin.hera')),
            ('View event log', reverse('admin:editors_eventlog_changelist')),
            ('View addon log', reverse('admin:devhub_activitylog_changelist')),
            ('Generate error', reverse('zadmin.generate-error')),
            ('Site Status', reverse('amo.monitor')),
        ],
    }
