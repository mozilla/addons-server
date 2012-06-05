from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from tower import ugettext as _

from access import acl
import amo
from amo.context_processors import get_collect_timings
from amo.urlresolvers import reverse
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
        account_links = []
        context['is_reviewer'] = acl.check_reviewer(request)
        if getattr(request, 'can_view_consumer', True):
            account_links = [
                {'text': _('Account History'),
                 'href': reverse('account.purchases')},
                {'text': _('Account Settings'),
                 'href': reverse('account.settings')},
            ]
        account_links += [
            {'text': _('Change Password'),
             'href': 'https://browserid.org/signin'},
            {'text': _('Log out'), 'href': reverse('users.logout')},
        ]
        if '/developers/' not in request.path:
            if amo_user.is_app_developer:
                tools_links.append({'text': _('My Submissions'),
                                    'href': reverse('mkt.developers.apps')})
            else:
                tools_links.append({'text': _('Developers'),
                                    'href': reverse('ecosystem.landing')})
        if '/reviewers/' not in request.path and context['is_reviewer']:
            tools_links.append({'text': _('Reviewer Tools'),
                                'href': reverse('reviewers.home')})
        if acl.action_allowed(request, 'Localizers', '%'):
            tools_links.append({'text': _('Localizer Tools'),
                                'href': '/localizers'})
        if acl.action_allowed(request, 'AccountLookup', '%'):
            tools_links.append({'text': _('Account Lookup'),
                                'href': reverse('acct_lookup.home')})
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
                   collect_timings_percent=get_collect_timings(),
                   is_admin=acl.action_allowed(request, 'Addons', 'Edit'))
    return context
