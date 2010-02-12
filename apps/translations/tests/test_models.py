# -*- coding: utf-8 -*-
from django.core.cache import cache
from django.utils import translation

from nose.tools import eq_

from test_utils import ExtraAppTestCase, trans_eq

from testapp.models import TranslatedModel, UntranslatedModel
from translations.models import Translation
from translations import widgets
from translations.query import order_by_translation


def ids(qs):
    return [o.id for o in qs]


class TranslationTestCase(ExtraAppTestCase):
    fixtures = ['testapp/test_models.json']
    extra_apps = ['translations.tests.testapp']

    def setUp(self):
        cache.clear()

    def test_fetch_translations(self):
        """Basic check of fetching translations in the current locale."""
        o = TranslatedModel.objects.get(id=1)
        trans_eq(o.name, 'some name', 'en-US')
        trans_eq(o.description, 'some description', 'en-US')

    def test_fetch_no_translations(self):
        """Make sure models with no translations aren't harmed."""
        o = UntranslatedModel.objects.get(id=1)
        eq_(o.number, 17)

    def test_fetch_translation_de_locale(self):
        """Check that locale fallbacks work."""
        try:
            translation.activate('de')
            o = TranslatedModel.objects.get(id=1)
            trans_eq(o.name, 'German!! (unst unst)', 'de')
            trans_eq(o.description, 'some description', 'en-US')
        finally:
            translation.deactivate()

    def test_create_translation(self):
        o = TranslatedModel.objects.create(name='english name')
        get_model = lambda: TranslatedModel.objects.get(id=o.id)
        trans_eq(o.name, 'english name', 'en-US')
        eq_(o.description, None)

        # Make sure the translation id is stored on the model, not the autoid.
        eq_(o.name.id, o.name_id)

        # Check that a different locale creates a new row with the same id.
        translation.activate('de')
        german = get_model()
        trans_eq(o.name, 'english name', 'en-US')

        german.name = u'Gemütlichkeit name'
        german.description = u'clöüserw description'
        german.save()

        trans_eq(german.name, u'Gemütlichkeit name', 'de')
        trans_eq(german.description, u'clöüserw description', 'de')

        # ids should be the same, autoids are different.
        eq_(o.name.id, german.name.id)
        assert o.name.autoid != german.name.autoid

        # Check that de finds the right translation.
        fresh_german = get_model()
        trans_eq(fresh_german.name, u'Gemütlichkeit name', 'de')
        trans_eq(fresh_german.description, u'clöüserw description', 'de')

        # Check that en-US has the right translations.
        translation.deactivate()
        english = get_model()
        trans_eq(english.name, 'english name', 'en-US')
        english.debug = True
        eq_(english.description, None)

        english.description = 'english description'
        english.save()

        fresh_english = get_model()
        trans_eq(fresh_english.description, 'english description', 'en-US')
        eq_(fresh_english.description.id, fresh_german.description.id)

    def test_update_translation(self):
        o = TranslatedModel.objects.get(id=1)
        translation_id = o.name.autoid

        o.name = 'new name'
        o.save()

        o = TranslatedModel.objects.get(id=1)
        trans_eq(o.name, 'new name', 'en-US')
        # Make sure it was an update, not an insert.
        eq_(o.name.autoid, translation_id)

    def test_create_with_dict(self):
        # Set translations with a dict.
        strings = {'en-US': 'right language', 'de': 'wrong language'}
        o = TranslatedModel.objects.create(name=strings)

        # Make sure we get the English text since we're in en-US.
        trans_eq(o.name, 'right language', 'en-US')

        # Check that de was set.
        translation.activate('de')
        o = TranslatedModel.objects.get(id=o.id)
        trans_eq(o.name, 'wrong language', 'de')

        # We're in de scope, so we should see the de text.
        de = TranslatedModel.objects.create(name=strings)
        trans_eq(o.name, 'wrong language', 'de')

        # Make sure en-US was still set.
        translation.deactivate()
        o = TranslatedModel.objects.get(id=de.id)
        trans_eq(o.name, 'right language', 'en-US')

    def test_update_with_dict(self):
        # There's existing en-US and de strings.
        strings = {'de': None, 'fr': 'oui'}
        get_model = lambda: TranslatedModel.objects.get(id=1)

        # Don't try checking that the model's name value is en-US.  It will be
        # one of the other locales, but we don't know which one.  You just set
        # the name to a dict, deal with it.
        get_model().name = strings

        # en-US was not touched.
        trans_eq(get_model().name, 'some name', 'en-US')

        # de was updated to NULL, so it falls back to en-US.
        translation.activate('de')
        trans_eq(get_model().name, 'some name', 'en-US')

        # fr was added.
        translation.activate('fr')
        trans_eq(get_model().name, 'oui', 'fr')

    def test_widget(self):
        strings = {'de': None, 'fr': 'oui'}
        o = TranslatedModel.objects.get(id=1)
        o.name = strings

        # Shouldn't see de since that's NULL now.
        ws = widgets.trans_widgets(o.name_id, lambda *args: None)
        eq_(sorted(dict(ws).keys()), ['en-us', 'fr'])

    def test_sorting(self):
        """Test translation comparisons in Python code."""
        b = Translation.new('bbbb', 'de')
        a = Translation.new('aaaa', 'de')
        c = Translation.new('cccc', 'de')
        eq_(sorted([c, a, b]), [a, b, c])

    def test_sorting_en(self):
        q = TranslatedModel.objects.all()
        expected = [4, 1, 3]

        eq_(ids(order_by_translation(q, 'name')), expected)
        eq_(ids(order_by_translation(q, '-name')), list(reversed(expected)))

    def test_sorting_mixed(self):
        translation.activate('de')
        q = TranslatedModel.objects.all()
        expected = [1, 4, 3]

        eq_(ids(order_by_translation(q, 'name')), expected)
        eq_(ids(order_by_translation(q, '-name')), list(reversed(expected)))

    def test_sorting_by_field(self):
        field = TranslatedModel._meta.get_field('default_locale')
        TranslatedModel.get_fallback = classmethod(lambda cls: field)

        translation.activate('de')
        q = TranslatedModel.objects.all()
        expected = [3, 1, 4]

        eq_(ids(order_by_translation(q, 'name')), expected)
        eq_(ids(order_by_translation(q, '-name')), list(reversed(expected)))

        del TranslatedModel.get_fallback


def test_translation_bool():
    t = lambda s: Translation(localized_string=s)

    assert bool(t('text')) is True
    assert bool(t(' ')) is False
    assert bool(t('')) is False


def test_widget_value_from_datadict():
    data = {'f_en-US': 'woo', 'f_de': 'herr', 'f_fr_delete': ''}
    actual = widgets.TranslationWidget().value_from_datadict(data, [], 'f')
    expected = {'en-US': 'woo', 'de': 'herr', 'fr': None}
    eq_(actual, expected)
