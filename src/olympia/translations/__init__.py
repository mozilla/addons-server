from django.conf import settings
from django.utils.translation import trans_real


LOCALES = [
    (trans_real.to_locale(k).replace('_', '-'), v) for k, v in settings.LANGUAGES
]
