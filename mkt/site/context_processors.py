from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.utils import translation
from django.utils.http import urlquote

from tower import ugettext as _
import waffle

import amo
from amo.urlresolvers import reverse
from amo.utils import memoize
from cake.urlresolvers import remora_url
from zadmin.models import get_config


def app(request):
    # We shouldn't need this for Marketplace, but for legacy purposes keep it.
    return {'APP': request.APP}


def static_url(request):
    return {'STATIC_URL': settings.STATIC_URL}


def i18n(request):
    return {'LANGUAGES': settings.LANGUAGES,
            'LANG': settings.LANGUAGE_URL_MAP.get(translation.get_language())
                    or translation.get_language(),
            'DIR': 'rtl' if translation.get_language_bidi() else 'ltr'}


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
    Storing global Marketplace-wide info. used in global headers
    (e.g., account links and settings).
    """
    account_links = []
    context = {}
    if request.user.is_authenticated() and hasattr(request, 'amo_user'):
        amo_user = request.amo_user
        account_links += [
            {'text': _('My Profile'),
             'href': amo_user.get_url_path()},
            {'text': _('Account Settings'), 'href': reverse('users.edit')},
            {'text': _('Log Out'),
             'href': remora_url('/users/logout?to=' + urlquote(request.path))},
        ]
        context['amo_user'] = request.amo_user
    else:
        context['amo_user'] = AnonymousUser()
    context.update(account_links=account_links,
                   settings=settings,
                   amo=amo,
                   ADMIN_MESSAGE=get_config('site_notice'),
                   collect_timings_percent=get_collect_timings())
    return context
