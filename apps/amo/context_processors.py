from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.utils import translation
from django.utils.http import urlquote

from tower import ugettext as _
import waffle

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

    tools_title = _('Tools')

    if request.user.is_authenticated() and hasattr(request, 'amo_user'):
        amo_user = request.amo_user
        account_links.append({
            'text': _('My Profile'),
            'href': request.user.get_profile().get_url_path(),
        })
        account_links.append({'text': _('Account Settings'),
                              'href': reverse('users.edit')})
        if not settings.APP_PREVIEW:
            account_links.append({
                'text': _('My Collections'),
                'href': reverse('collections.user', args=[amo_user.username])})

            if amo_user.favorite_addons:
                account_links.append(
                    {'text': _('My Favorites'),
                     'href': reverse('collections.detail',
                                     args=[amo_user.username, 'favorites'])})

        if waffle.switch_is_active('marketplace'):
            account_links.append({'text': _('My Purchases'),
                                  'href': reverse('users.purchases')})
        account_links.append({
            'text': _('Log out'),
            'href': remora_url('/users/logout?to=' + urlquote(request.path)),
        })

        if not settings.APP_PREVIEW:
            if request.amo_user.is_developer:
                tools_links.append({'text': _('Manage My Add-ons'),
                                    'href': reverse('devhub.addons')})
            tools_links.append({'text': _('Submit a New Add-on'),
                                'href': reverse('devhub.submit.1')})

        if waffle.flag_is_active(request, 'accept-webapps'):
            if settings.APP_PREVIEW or request.amo_user.is_developer:
                tools_links.append({'text': _('Manage My Apps'),
                                    'href': reverse('devhub.apps')})
            tools_links.append({'text': _('Submit a New App'),
                                'href': reverse('devhub.submit_apps.1')})

        if waffle.flag_is_active(request, 'submit-personas'):
            # TODO(cvan)(fligtar): Do we want this here?
            tools_links.append({'text': 'Submit a New Persona',
                                'href': reverse('devhub.personas.submit')})

        if not settings.APP_PREVIEW:
            tools_links.append({'text': _('Developer Hub'),
                                'href': reverse('devhub.index')})

        if acl.action_allowed(request, 'Editors', '%'):
            tools_links.append({'text': _('Editor Tools'),
                                'href': reverse('editors.home')})
        if acl.action_allowed(request, 'Localizers', '%'):
            tools_links.append({'text': _('Localizer Tools'),
                                'href': '/localizers'})
        if acl.action_allowed(request, 'Admin', '%'):
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
