from django.conf import settings
from django.utils import translation

import jingo
from mock import Mock
from nose.tools import eq_

from translations.helpers import locale_html
from translations.models import PurifiedTranslation


def super():
    jingo.load_helpers()


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
    for lang in settings.RTL_LANGUAGES:
        testfield.locale = lang
        s = locale_html(testfield)
        eq_(s, ' lang="%s" dir="rtl"' % testfield.locale)


def test_empty_locale_html():
    """locale_html must still work if field is None."""
    s = locale_html(None)
    assert not s, 'locale_html on None must be empty.'


def test_truncate_purified_field():
    s = '<p>one</p><p>two</p>'
    t = PurifiedTranslation(localized_string=s)
    actual = jingo.env.from_string('{{ s|truncate(6) }}').render(s=t)
    eq_(actual, s)
