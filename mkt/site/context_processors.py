from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from tower import ugettext as _

import amo
from amo.context_processors import get_collect_timings
from amo.urlresolvers import reverse
from access import acl
import mkt
from zadmin.models import get_config


def global_settings(request):
    """Store global Marketplace-wide info. used in the header."""
    account_links = []
    tools_links = []
    context = {}

    tools_title = _('Tools')

    if request.user.is_authenticated() and hasattr(request, 'amo_user'):
        amo_user = request.amo_user
        account_links = [
            {'text': _('Change Password'), 'href': 'https://browserid.org/'},
            {'text': _('Log out'), 'href': reverse('users.logout')},
        ]
# Not right now. This leads to a rabbit hole of issues. See bug 729751
# or ask andym for more.
#        if acl.check_reviewer(request):
#            tools_links.append({'text': _('Editor Tools'),
#                                'href': reverse('editors.home')})
        if acl.action_allowed(request, 'Localizers', '%'):
            tools_links.append({'text': _('Localizer Tools'),
                                'href': '/localizers'})
        if acl.action_allowed(request, 'Admin', '%'):
            tools_links.append({'text': _('Admin Tools'),
                                'href': reverse('zadmin.home')})

        context['amo_user'] = amo_user
    else:
        context['amo_user'] = AnonymousUser()

    context.update(account_links=account_links,
                   settings=settings,
                   amo=amo, mkt=mkt,
                   tools_links=tools_links,
                   tools_title=tools_title,
                   ADMIN_MESSAGE=get_config('site_notice'),
                   collect_timings_percent=get_collect_timings())
    return context
