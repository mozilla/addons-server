from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.utils.http import urlquote

from tower import ugettext as _

import amo
from amo.context_processors import get_collect_timings
from amo.urlresolvers import reverse
from cake.urlresolvers import remora_url
from zadmin.models import get_config


def global_settings(request):
    """Store global Marketplace-wide info. used in the header."""
    account_links = []
    context = {}
    if request.user.is_authenticated() and hasattr(request, 'amo_user'):
        amo_user = request.amo_user
        account_links += [
            {'text': _('My Profile'),
             'href': amo_user.get_url_path()},
            {'text': _('Account Settings'), 'href': reverse('users.edit')},
            {'text': _('Log Out'),
             'href': remora_url('/users/logout?to=' + urlquote(request.path))},
        ]
        context['amo_user'] = amo_user
    else:
        context['amo_user'] = AnonymousUser()
    context.update(account_links=account_links,
                   settings=settings,
                   amo=amo,
                   ADMIN_MESSAGE=get_config('site_notice'),
                   collect_timings_percent=get_collect_timings())
    return context
