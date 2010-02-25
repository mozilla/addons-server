import random

from django.conf import settings
from django.utils import translation

from mock import Mock
from nose.tools import eq_

from translations.helpers import locale_html


def test_locale_html():
    """Test HTML attributes for languages different than the site language"""
    testfield = Mock()

    # same language: no need for attributes
    this_lang = translation.get_language()
    testfield.locale = this_lang
    s = locale_html(testfield)
    assert not s, 'no special HTML attributes for site language'

    # non-rtl language
    testfield.locale = 'de'
    s = locale_html(testfield)
    eq_(s, ' lang="de" dir="ltr"')

    # rtl language
    testfield.locale = random.choice(settings.RTL_LANGUAGES)
    s = locale_html(testfield)
    eq_(s, ' lang="%s" dir="rtl"' % testfield.locale)
