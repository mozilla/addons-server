from django.conf import settings
from django.utils.translation import trans_real

from jinja2.filters import do_dictsort


LOCALES = [
    (trans_real.to_locale(k).replace('_', '-'), v)
    for k, v in do_dictsort(settings.LANGUAGES)
]
