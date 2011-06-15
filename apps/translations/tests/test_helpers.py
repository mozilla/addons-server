from django.conf import settings
from django.utils import translation

import jingo
from mock import Mock
from nose.tools import eq_

from translations import helpers
from translations.models import PurifiedTranslation


def super():
    jingo.load_helpers()


def test_locale_html():
    """Test HTML attributes for languages different than the site language"""
    testfield = Mock()

    # same language: no need for attributes
    this_lang = translation.get_language()
    testfield.locale = this_lang
    s = helpers.locale_html(testfield)
    assert not s, 'no special HTML attributes for site language'

    # non-rtl language
    testfield.locale = 'de'
    s = helpers.locale_html(testfield)
    eq_(s, ' lang="de" dir="ltr"')

    # rtl language
    for lang in settings.RTL_LANGUAGES:
        testfield.locale = lang
        s = helpers.locale_html(testfield)
        eq_(s, ' lang="%s" dir="rtl"' % testfield.locale)


def test_locale_html_xss():
    """Test for nastiness-removal in the transfield's locale"""
    testfield = Mock()

    # same language: no need for attributes
    testfield.locale = '<script>alert(1)</script>'
    s = helpers.locale_html(testfield)
    assert '<script>' not in s
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in s


def test_empty_locale_html():
    """locale_html must still work if field is None."""
    s = helpers.locale_html(None)
    assert not s, 'locale_html on None must be empty.'


def test_truncate_purified_field():
    s = '<i>one</i><i>two</i>'
    t = PurifiedTranslation(localized_string=s)
    actual = jingo.env.from_string('{{ s|truncate(6) }}').render(s=t)
    eq_(actual, s)


def test_truncate_purified_field_xss():
    """Truncating should not introduce xss issues."""
    s = 'safe <script>alert("omg")</script>'
    t = PurifiedTranslation(localized_string=s)
    actual = jingo.env.from_string('{{ s|truncate(100) }}').render(s=t)
    eq_(actual, 'safe &lt;script&gt;alert("omg")&lt;/script&gt;')
    actual = jingo.env.from_string('{{ s|truncate(5) }}').render(s=t)
    eq_(actual, 'safe ...')


def test_clean():
    # Links are not mangled, bad HTML is escaped, newlines are slimmed.
    s = '<ul><li><a href="#woo">\n\nyeah</a></li>\n\n<li><script></li></ul>'
    eq_(helpers.clean(s),
        '<ul><li><a href="#woo">\n\nyeah</a></li><li>&lt;script&gt;</li></ul>')


def test_clean_in_template():
    s = '<a href="#woo">yeah</a>'
    eq_(jingo.env.from_string('{{ s|clean }}').render(s=s), s)
