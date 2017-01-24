from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.utils.translation import (
    ugettext as _, get_language, get_language_bidi)
from django.utils.http import urlquote

from olympia import amo
from olympia.amo.urlresolvers import reverse
from olympia.access import acl
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

    tools_title = _('Tools')
    is_reviewer = False

    if request.user.is_authenticated():
        user = request.user

        profile = request.user
        is_reviewer = (acl.check_addons_reviewer(request) or
                       acl.check_personas_reviewer(request))

        account_links.append({'text': _('My Profile'),
                              'href': profile.get_url_path()})
        if user.is_artist:
            account_links.append({'text': _('My Themes'),
                                  'href': profile.get_user_url('themes')})

        account_links.append({'text': _('Account Settings'),
                              'href': reverse('users.edit')})
        account_links.append({
            'text': _('My Collections'),
            'href': reverse('collections.user', args=[user.username])})

        if user.favorite_addons:
            account_links.append(
                {'text': _('My Favorites'),
                 'href': reverse('collections.detail',
                                 args=[user.username, 'favorites'])})

        account_links.append({
            'text': _('Log out'),
            'href': reverse('users.logout') + '?to=' + urlquote(request.path),
        })

        if request.user.is_developer:
            tools_links.append({'text': _('Manage My Submissions'),
                                'href': reverse('devhub.addons')})
        links = [
            {'text': _('Submit a New Add-on'),
             'href': reverse('devhub.submit.agreement')},
            {'text': _('Submit a New Theme'),
             'href': reverse('devhub.themes.submit')},
            {'text': _('Developer Hub'),
             'href': reverse('devhub.index')},
        ]
        links.append({'text': _('Manage API Keys'),
                      'href': reverse('devhub.api_key')})

        tools_links += links
        if is_reviewer:
            tools_links.append({'text': _('Reviewer Tools'),
                                'href': reverse('editors.home')})
        if (acl.action_allowed(request, 'Admin', '%') or
                acl.action_allowed(request, 'AdminTools', 'View')):
            tools_links.append({'text': _('Admin Tools'),
                                'href': reverse('zadmin.home')})

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
