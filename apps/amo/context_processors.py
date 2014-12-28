from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.utils import translation
from django.utils.http import urlquote

import waffle
from cache_nuggets.lib import memoize
from tower import ugettext as _

import amo
from amo.urlresolvers import remora_url, reverse
from access import acl
from zadmin.models import get_config


def app(request):
    return {'APP': getattr(request, 'APP', None)}


def static_url(request):
    return {'STATIC_URL': settings.STATIC_URL}


def i18n(request):
    return {'LANGUAGES': settings.LANGUAGES,
            'LANG': (
                settings.LANGUAGE_URL_MAP.get(translation.get_language())
                or translation.get_language()),
            'DIR': 'rtl' if translation.get_language_bidi() else 'ltr',
            }


@memoize('collect-timings')
def get_collect_timings():
    # The flag has to be enabled for everyone and then we'll use that
    # percentage in the pages.
    percent = 0
    try:
        flag = waffle.models.Flag.objects.get(name='collect-timings')
        if flag.everyone and flag.percent:
            percent = float(flag.percent) / 100.0
    except waffle.models.Flag.DoesNotExist:
        pass
    return percent


def global_settings(request):
    """
    Storing standard AMO-wide information used in global headers, such as
    account links and settings.
    """
    account_links = []
    tools_links = []
    context = {}

    tools_title = _('Tools')
    is_reviewer = False

    if request.user.is_authenticated():
        amo_user = request.amo_user
        profile = request.user
        is_reviewer = (acl.check_addons_reviewer(request) or
                       acl.check_personas_reviewer(request))

        account_links.append({'text': _('My Profile'),
                              'href': profile.get_url_path()})
        if amo_user.is_artist:
            account_links.append({'text': _('My Themes'),
                                  'href': profile.get_user_url('themes')})

        account_links.append({'text': _('Account Settings'),
                              'href': reverse('users.edit')})
        account_links.append({
            'text': _('My Collections'),
            'href': reverse('collections.user', args=[amo_user.username])})

        if amo_user.favorite_addons:
            account_links.append(
                {'text': _('My Favorites'),
                 'href': reverse('collections.detail',
                                 args=[amo_user.username, 'favorites'])})

        account_links.append({
            'text': _('Log out'),
            'href': remora_url('/users/logout?to=' + urlquote(request.path)),
        })

        if request.amo_user.is_developer:
            tools_links.append({'text': _('Manage My Submissions'),
                                'href': reverse('devhub.addons')})
        tools_links += [
            {'text': _('Submit a New Add-on'),
             'href': reverse('devhub.submit.1')},
            {'text': _('Submit a New Theme'),
             'href': reverse('devhub.themes.submit')},
            {'text': _('Developer Hub'),
             'href': reverse('devhub.index')},
        ]

        if is_reviewer:
            tools_links.append({'text': _('Editor Tools'),
                                'href': reverse('editors.home')})
        if acl.action_allowed(request, 'L10nTools', 'View'):
            tools_links.append({'text': _('Localizer Tools'),
                                'href': '/localizers'})
        if (acl.action_allowed(request, 'Admin', '%') or
                acl.action_allowed(request, 'AdminTools', 'View')):
            tools_links.append({'text': _('Admin Tools'),
                                'href': reverse('zadmin.home')})

        context['amo_user'] = request.amo_user
    else:
        context['amo_user'] = AnonymousUser()

    context.update({'account_links': account_links,
                    'settings': settings, 'amo': amo,
                    'tools_links': tools_links,
                    'tools_title': tools_title,
                    'ADMIN_MESSAGE': get_config('site_notice'),
                    'collect_timings_percent': get_collect_timings(),
                    'is_reviewer': is_reviewer})
    return context
