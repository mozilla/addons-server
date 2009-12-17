# -*- coding: utf-8 -*-
from django.utils import translation
from nose.tools import eq_

from test_utils import ExtraAppTestCase, trans_eq

from testapp.models import TranslatedModel, UntranslatedModel
from translations.models import Translation, TranslationSequence


class TranslationTestCase(ExtraAppTestCase):
    fixtures = ['testapp/test_models.json']
    extra_apps = ['translations.tests.testapp']

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


def test_translation_bool():
    t = lambda s: Translation(localized_string=s)

    assert bool(t('text')) is True
    assert bool(t(' ')) is False
    assert bool(t('')) is False
