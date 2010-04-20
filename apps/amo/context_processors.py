from django.conf import settings
from django.utils import translation
from tower import ugettext as _
from django.utils.http import urlquote

import amo
from amo.urlresolvers import reverse
from access import acl


def app(request):
    return {'APP': request.APP}


def i18n(request):
    return {'LANGUAGES': settings.LANGUAGES,
            'LANG': translation.get_language(),
            'DIR': 'rtl' if translation.get_language_bidi() else 'ltr',
            }


def global_settings(request):
    """
    Storing standard AMO-wide information used in global headers, such as
    account links and settings.
    """
    account_links = []
    tools_links = []

    if request.user.is_authenticated():
        # TODO(jbalogh): reverse links
        account_links.append({
            'text': _('View Profile'),
            'href': request.user.get_profile().get_url_path(),
        })
        account_links.append({'text': _('Edit Profile'),
                              'href': '/users/edit'})
        if request.amo_user.is_developer:
            account_links.append({'text': _('My Add-ons'),
                                  'href': '/developers/addons'})

        account_links.append({'text': _('My Collections'),
                              'href': '/collections/mine'})

        account_links.append({
            'text': _('Log out'),
            'href': '/users/logout?to=' + urlquote(request.path),
        })

        tools_links.append({'text': _('Developer Hub'),
                            'href': '/developers'})
        if acl.action_allowed(request, 'Editors', '%'):
            tools_links.append({'text': _('Editor Tools'),
                                'href': '/editors'})
        if acl.action_allowed(request, 'Localizers', '%'):
            tools_links.append({'text': _('Localizer Tools'),
                                'href': '/localizers'})
        if acl.action_allowed(request, 'Admin', '%'):
            tools_links.append({'text': _('Admin Tools'),
                                'href': reverse('zadmin.home')})


    return {'account_links': account_links, 'settings': settings, 'amo': amo,
            'tools_links': tools_links}
