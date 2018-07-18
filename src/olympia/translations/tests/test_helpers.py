from django.conf import settings
from django.utils import translation

import pytest

from mock import Mock, patch

from olympia.addons.models import Addon
from olympia.amo.tests import TestCase
from olympia.amo.utils import from_string
from olympia.translations.fields import save_signal
from olympia.translations.models import PurifiedTranslation
from olympia.translations.templatetags import jinja_helpers
from olympia.translations.tests.testapp.models import TranslatedModel


pytestmark = pytest.mark.django_db


def test_locale_html():
    """Test HTML attributes for languages different than the site language"""
    testfield = Mock()

    # same language: no need for attributes
    this_lang = translation.get_language()
    testfield.locale = this_lang
    s = jinja_helpers.locale_html(testfield)
    assert not s, 'no special HTML attributes for site language'

    # non-rtl language
    testfield.locale = 'de'
    s = jinja_helpers.locale_html(testfield)
    assert s == ' lang="de" dir="ltr"'

    # rtl language
    for lang in settings.LANGUAGES_BIDI:
        testfield.locale = lang
        s = jinja_helpers.locale_html(testfield)
        assert s == ' lang="%s" dir="rtl"' % testfield.locale


def test_locale_html_xss():
    """Test for nastiness-removal in the transfield's locale"""
    testfield = Mock()

    # same language: no need for attributes
    testfield.locale = '<script>alert(1)</script>'
    s = jinja_helpers.locale_html(testfield)
    assert '<script>' not in s
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in s


def test_empty_locale_html():
    """locale_html must still work if field is None."""
    s = jinja_helpers.locale_html(None)
    assert not s, 'locale_html on None must be empty.'


def test_truncate_purified_field():
    s = '<i>one</i><i>two</i>'
    t = PurifiedTranslation(localized_string=s)
    actual = from_string('{{ s|truncate(6) }}').render({'s': t})
    assert actual == s


def test_truncate_purified_field_xss():
    """Truncating should not introduce xss issues."""
    s = 'safe <script>alert("omg")</script>'
    t = PurifiedTranslation(localized_string=s)
    actual = from_string('{{ s|truncate(100) }}').render({'s': t})
    assert actual == 'safe &lt;script&gt;alert("omg")&lt;/script&gt;'
    actual = from_string('{{ s|truncate(5) }}').render({'s': t})
    assert actual == 'safe ...'


def test_clean():
    # Links are not mangled, bad HTML is escaped, newlines are slimmed.
    s = '<ul><li><a href="#woo">\n\nyeah</a></li>\n\n<li><script></li></ul>'
    assert jinja_helpers.clean(s) == (
        '<ul><li><a href="#woo">\n\nyeah</a></li><li>&lt;script&gt;</li></ul>'
    )


def test_clean_in_template():
    s = '<a href="#woo">yeah</a>'
    assert from_string('{{ s|clean }}').render({'s': s}) == s


def test_clean_strip_all_html():
    s = '<a href="#woo">yeah</a>'

    expected = 'yeah'
    assert from_string('{{ s|clean(true) }}').render({'s': s}) == expected


def test_no_links():
    template = from_string('{{ s|no_links }}')

    s = 'a <a href="http://url.link">http://example.com</a>, http://text.link'
    expected = 'a http://example.com, http://text.link'
    assert template.render({'s': s}) == expected

    # Bad markup.
    s = '<http://bad.markup.com'
    assert template.render({'s': s}) == ''

    # Bad markup.
    s = 'some text <http://bad.markup.com'
    assert template.render({'s': s}) == 'some text'


def test_l10n_menu():
    # No remove_locale_url provided.
    menu = jinja_helpers.l10n_menu({})
    assert 'data-rm-locale=""' in menu, menu

    # Specific remove_locale_url provided (eg for user).
    menu = jinja_helpers.l10n_menu({}, remove_locale_url='/some/url/')
    assert 'data-rm-locale="/some/url/"' in menu, menu

    # Use the remove_locale_url taken from the addon in the context.
    menu = jinja_helpers.l10n_menu(
        {'addon': Addon()}, remove_locale_url='some/url/'
    )
    assert 'data-rm-locale="/en-US/developers/addon/None/rmlocale"' in menu


@patch.object(settings, 'AMO_LANGUAGES', ('de', 'en-US', 'es', 'fr', 'pt-BR'))
class TestAllLocales(TestCase):
    def test_all_locales_none(self):
        addon = None
        field_name = 'description'
        assert jinja_helpers.all_locales(addon, field_name) is None

        addon = Mock()
        field_name = 'description'
        del addon.description
        assert jinja_helpers.all_locales(addon, field_name) is None

    def test_all_locales(self):
        obj = TranslatedModel()
        obj.description = {'en-US': 'There', 'es': 'Is No', 'fr': 'Spoon'}
        # Pretend the TranslateModel instance was saved to force Translation
        # objects to be saved.
        save_signal(sender=TranslatedModel, instance=obj)

        result = jinja_helpers.all_locales(obj, 'description')
        assert u'<div class="trans" data-name="description">' in result
        assert u'<span lang="en-us">There</span>' in result
        assert u'<span lang="es">Is No</span>' in result
        assert u'<span lang="fr">Spoon</span>' in result

    def test_all_locales_empty(self):
        obj = TranslatedModel()
        obj.description = {'en-US': 'There', 'es': 'Is No', 'fr': ''}
        # Pretend the TranslateModel instance was saved to force Translation
        # objects to be saved.
        save_signal(sender=TranslatedModel, instance=obj)

        result = jinja_helpers.all_locales(obj, 'description')
        assert u'<div class="trans" data-name="description">' in result
        assert u'<span lang="en-us">There</span>' in result
        assert u'<span lang="es">Is No</span>' in result
        assert u'<span lang="fr"></span>' in result

        result = jinja_helpers.all_locales(
            obj, 'description', prettify_empty=True
        )
        assert u'<div class="trans" data-name="description">' in result
        assert u'<span lang="en-us">There</span>' in result
        assert u'<span lang="es">Is No</span>' in result
        assert u'<span class="empty" lang="fr">None</span>' in result
