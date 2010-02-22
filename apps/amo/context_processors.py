from django.conf import settings
from django.utils import translation
from l10n import ugettext as _
from django.utils.http import urlquote

import amo


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

    if request.user.is_authenticated():
        link = {}
        link['text'] = _('View Profile')
        link['href'] = request.user.get_profile().get_absolute_url()
        account_links.append(link)

        link = {}
        link['text'] = _('Edit Profile')
        # XXX: We need to generate these urls
        link['href'] = '/users/edit'
        account_links.append(link)

        # Todo - add addonCount -> /developers/addons
        #  - add collections /collections/mine

        link = {}
        link['text'] = _('Log out')
        # XXX: We need to generate these urls

        link['href'] = '/users/logout?to=' + urlquote(request.path)
        account_links.append(link)

    return {'account_links': account_links, 'settings': settings, 'amo': amo}
