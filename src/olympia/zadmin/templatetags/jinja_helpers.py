from django_jinja import library

from olympia.amo.urlresolvers import reverse
from olympia.zadmin.models import get_config as zadmin_get_config


@library.global_function
def admin_site_links():
    return {
        'addons': [
            ('Fake mail', reverse('admin:amo_fakeemail_changelist')),
            ('Replacement Addons', reverse(
                'admin:addons_replacementaddon_changelist')),
        ],
        'users': [
            ('Configure groups', reverse('admin:access_group_changelist')),
        ],
        'settings': [
            ('Django admin pages', reverse('zadmin.home')),
        ],
        'tools': [
            ('View addon log',
             reverse('admin:activity_activitylog_changelist')),
        ],
    }


@library.global_function
def get_config(key):
    return zadmin_get_config(key)
