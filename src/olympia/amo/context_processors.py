from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.utils.http import urlquote
from django.utils.translation import get_language, get_language_bidi, ugettext

import waffle

from olympia import amo
from olympia.access import acl
from olympia.amo.urlresolvers import reverse
from olympia.zadmin.models import get_config


def app(request):
    return {'APP': getattr(request, 'APP', None)}


def static_url(request):
    return {'CDN_HOST': settings.CDN_HOST,
            'STATIC_URL': settings.STATIC_URL}


def i18n(request):
    lang = get_language()
    return {'LANGUAGES': settings.LANGUAGES,
            'LANG': settings.LANGUAGE_URL_MAP.get(lang) or lang,
            'DIR': 'rtl' if get_language_bidi() else 'ltr'}


def global_settings(request):
    """
    Storing standard AMO-wide information used in global headers, such as
    account links and settings.
    """
    account_links = []
    tools_links = []
    context = {}

    tools_title = ugettext('Tools')
    is_reviewer = False

    if request.user.is_authenticated():
        is_reviewer = acl.is_user_any_kind_of_reviewer(request.user)

        account_links.append({'text': ugettext('My Profile'),
                              'href': request.user.get_url_path()})
        if request.user.is_artist:
            account_links.append({'text': ugettext('My Themes'),
                                  'href': request.user.get_themes_url_path()})

        account_links.append({'text': ugettext('Account Settings'),
                              'href': reverse('users.edit')})
        account_links.append({
            'text': ugettext('My Collections'),
            'href': reverse('collections.user', args=[request.user.username])})

        if request.user.favorite_addons:
            account_links.append(
                {'text': ugettext('My Favorites'),
                 'href': reverse('collections.detail',
                                 args=[request.user.username, 'favorites'])})

        account_links.append({
            'text': ugettext('Log out'),
            'href': reverse('users.logout') + '?to=' + urlquote(request.path),
        })

        if request.user.is_developer:
            tools_links.append({'text': ugettext('Manage My Submissions'),
                                'href': reverse('devhub.addons')})
        tools_links.append(
            {'text': ugettext('Submit a New Add-on'),
             'href': reverse('devhub.submit.agreement')})
        no_more_lwt = waffle.switch_is_active('disable-lwt-uploads')
        tools_links.append(
            {'text': ugettext('Submit a New Theme'),
             'href': reverse('devhub.submit.agreement' if no_more_lwt
                             else 'devhub.themes.submit')})
        tools_links.append(
            {'text': ugettext('Developer Hub'),
             'href': reverse('devhub.index')})
        tools_links.append(
            {'text': ugettext('Manage API Keys'),
             'href': reverse('devhub.api_key')}
        )

        if is_reviewer:
            tools_links.append({'text': ugettext('Reviewer Tools'),
                                'href': reverse('reviewers.dashboard')})
        if acl.action_allowed(request, amo.permissions.ANY_ADMIN):
            tools_links.append({'text': ugettext('Admin Tools'),
                                'href': reverse('zadmin.index')})

        context['user'] = request.user
    else:
        context['user'] = AnonymousUser()

    context.update({'account_links': account_links,
                    'settings': settings,
                    'amo': amo,
                    'tools_links': tools_links,
                    'tools_title': tools_title,
                    'ADMIN_MESSAGE': get_config('site_notice'),
                    'is_reviewer': is_reviewer})
    return context
