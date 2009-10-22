from django.conf import settings
from django.utils import translation


def i18n(request):
    return {'LANGUAGES': settings.LANGUAGES,
            'LANG': translation.get_language(),
            'DIR': 'rtl' if translation.get_language_bidi() else 'ltr',
            }
