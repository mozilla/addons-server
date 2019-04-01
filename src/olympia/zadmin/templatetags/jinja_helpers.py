from django_jinja import library

from olympia.amo.urlresolvers import reverse
from olympia.zadmin.models import get_config as zadmin_get_config


@library.global_function
def admin_site_links():
    return {
        'addons': [
            ('Search for add-ons by name or id',
             reverse('zadmin.addon-search')),
            ('Featured add-ons', reverse('zadmin.features')),
            ('Monthly Pick', reverse('zadmin.monthly_pick')),
            ('Fake mail', reverse('zadmin.mail')),
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
        ],
        'tools': [
            ('Manage elasticsearch', reverse('zadmin.elastic')),
            ('View addon log',
             reverse('admin:activity_activitylog_changelist')),
        ],
    }


@library.global_function
def get_config(key):
    return zadmin_get_config(key)
