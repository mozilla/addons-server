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
    footer_links = []
    context = {}

    tools_title = _('Tools')

    if request.user.is_authenticated() and getattr(request, 'amo_user', None):
        amo_user = request.amo_user
        context['is_reviewer'] = acl.check_reviewer(request)
        account_links = [
            # TODO: Coming soon with payments.
            # {'text': _('Account History'),
            #  'href': reverse('account.purchases')},
            {'text': _('Account Settings'),
             'href': reverse('account.settings')},
            {'text': _('Change Password'),
             'href': 'https://login.persona.org/signin'},
            {'text': _('Sign out'), 'href': reverse('users.logout')},
        ]
        if '/developers/' not in request.path:
            tools_links.append({'text': _('Developer Hub'),
                                'href': reverse('ecosystem.landing')})
            if amo_user.is_app_developer:
                tools_links.append({'text': _('My Submissions'),
                                    'href': reverse('mkt.developers.apps')})
        if '/reviewers/' not in request.path and context['is_reviewer']:
            footer_links.append({
                'text': _('Reviewer Tools'),
                'href': reverse('reviewers.apps.queue_pending'),
            })
        if acl.action_allowed(request, 'Localizers', '%'):
            footer_links.append({'text': _('Localizer Tools'),
                                'href': '/localizers'})
        if acl.action_allowed(request, 'AccountLookup', '%'):
            footer_links.append({'text': _('Lookup Tool'),
                                'href': reverse('lookup.home')})
        if acl.action_allowed(request, 'Admin', '%'):
            footer_links.append({'text': _('Admin Tools'),
                                'href': reverse('zadmin.home')})

        tools_links += footer_links

        context['amo_user'] = amo_user
        logged = True
    else:
        context['amo_user'] = AnonymousUser()
        logged = False

    DESKTOP = request.TABLET or not request.MOBILE

    context.update(account_links=account_links,
                   settings=settings,
                   amo=amo, mkt=mkt,
                   APP=amo.FIREFOX,
                   tools_links=tools_links,
                   tools_title=tools_title,
                   footer_links=footer_links,
                   ADMIN_MESSAGE=get_config('site_notice'),
                   collect_timings_percent=get_collect_timings(),
                   is_admin=acl.action_allowed(request, 'Addons', 'Edit'),
                   DESKTOP=DESKTOP,
                   logged=logged)
    return context
