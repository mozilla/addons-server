from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.utils import translation
from django.utils.http import urlquote

from tower import ugettext as _

import amo
from amo.urlresolvers import reverse
from access import acl
from cake.urlresolvers import remora_url
from zadmin.models import get_config


def app(request):
    return {'APP': request.APP}


def static_url(request):
    return {'STATIC_URL': settings.STATIC_URL}


def i18n(request):
    return {'LANGUAGES': settings.LANGUAGES,
            'LANG': settings.LANGUAGE_URL_MAP.get(translation.get_language())
                    or translation.get_language(),
            'DIR': 'rtl' if translation.get_language_bidi() else 'ltr',
            }


def global_settings(request):
    """
    Storing standard AMO-wide information used in global headers, such as
    account links and settings.
    """
    account_links = []
    tools_links = []
    context = {}

    tools_title = _('Developer')

    if request.user.is_authenticated() and request.amo_user:
        amo_user = request.amo_user
        account_links.append({
            'text': _('View Profile'),
            'href': request.user.get_profile().get_url_path(),
        })
        account_links.append({'text': _('Edit Profile'),
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
            tools_links.append({'text': _('Manage My Add-ons'),
                                'href': reverse('devhub.addons')})

            tools_links.append({'text': _('Submit a New Add-on'),
                                'href': reverse('devhub.submit.1')})

        tools_links.append({'text': _('Developer Hub'),
                            'href': reverse('devhub.index')})

        if acl.action_allowed(request, 'Editors', '%'):
            tools_title = _('Tools')
            tools_links.append({'text': _('Editor Tools'),
                                'href': reverse('editors.home')})
        if acl.action_allowed(request, 'Localizers', '%'):
            tools_title = _('Tools')
            tools_links.append({'text': _('Localizer Tools'),
                                'href': '/localizers'})
        if acl.action_allowed(request, 'Admin', '%'):
            tools_title = _('Tools')
            tools_links.append({'text': _('Admin Tools'),
                                'href': reverse('zadmin.home')})

        context['amo_user'] = request.amo_user
    else:
        context['amo_user'] = AnonymousUser()

    context.update({'account_links': account_links,
                    'settings': settings, 'amo': amo,
                    'tools_links': tools_links,
                    'tools_title': tools_title,
                    'ADMIN_MESSAGE': get_config('site_notice')})
    return context
