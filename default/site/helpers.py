from django.conf import settings

from jingo import register

from amo.helpers import url

from mkt.site.helpers import admin_site_links as mkt_admin_site_links


@register.function
def admin_site_links():
    if settings.MARKETPLACE:
        return mkt_admin_site_links()
    return {
        'addons': [
            ('Search for add-ons by name or id', url('zadmin.addon-search')),
            ('Featured add-ons', url('zadmin.features')),
            ('Discovery Pane promo modules', url('discovery.module_admin')),
            ('Monthly Pick', url('zadmin.monthly_pick')),
            ('Upgrade jetpack add-ons', url('zadmin.jetpack')),
            ('Bulk add-on validation', url('zadmin.validation')),
            ('Fake mail', url('zadmin.mail')),
            ('Flagged reviews', url('zadmin.flagged')),
            ('ACR Reports', url('zadmin.compat')),
            ('Email Add-on Developers', url('zadmin.email_devs')),
        ],
        'users': [
            ('Configure groups', url('admin:access_group_changelist')),
        ],
        'settings': [
            ('View site settings', url('zadmin.settings')),
            ('Django admin pages', url('zadmin.home')),
            ('Site Events', url('zadmin.site_events')),
        ],
        'tools': [
            ('View request environment', url('amo.env')),
            ('Manage elasticsearch', url('zadmin.elastic')),
            ('Purge data from memcache', url('zadmin.memcache')),
            ('Purge pages from zeus', url('zadmin.hera')),
            ('Create a new OAuth Consumer',
             url('zadmin.oauth-consumer-create')),
            ('View event log', url('admin:editors_eventlog_changelist')),
            ('View addon log', url('admin:devhub_activitylog_changelist')),
            ('Generate error', url('zadmin.generate-error')),
            ('Site Status', url('amo.monitor')),
        ],
    }
