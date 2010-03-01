# -*- coding: utf-8 -*-
from django import test
from django.utils import translation

import jinja2
from nose.tools import eq_
from test_utils import ExtraAppTestCase, trans_eq

from testapp.models import TranslatedModel, UntranslatedModel, FancyModel
from translations.models import (Translation, PurifiedTranslation,
                                 TranslationSequence)
from translations import widgets
from translations.query import order_by_translation


def ids(qs):
    return [o.id for o in qs]


class TranslationSequenceTestCase(test.TestCase):
    """
    Make sure automatic translation sequence generation works
    as expected.
    """

    def test_empty_translations_seq(self):
        """Make sure we can handle an empty translation sequence table."""
        TranslationSequence.objects.all().delete()
        newtrans = Translation.new('abc', 'en-us')
        newtrans.save()
        assert newtrans.id > 0, (
            'Empty translation table should still generate an ID.')

    def test_single_translation_sequence(self):
        """Make sure we only ever have one translation sequence."""
        TranslationSequence.objects.all().delete()
        eq_(TranslationSequence.objects.count(), 0)
        for i in range(5):
            newtrans = Translation.new(str(i), 'en-us')
            newtrans.save()
            eq_(TranslationSequence.objects.count(), 1)

    def test_translation_sequence_increases(self):
        """Make sure translation sequence increases monotonically."""
        newtrans1 = Translation.new('abc', 'en-us')
        newtrans1.save()
        newtrans2 = Translation.new('def', 'de')
        newtrans2.save()
        assert newtrans2.pk > newtrans1.pk, (
            'Translation sequence needs to keep increasing.')


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

    def test_new_purified_field(self):
        # This is not a full test of the html sanitizing.  We expect the
        # underlying bleach library to have full tests.
        s = '<a id=xx href="http://xxx.com">yay</a> <i>http://yyy.com</i>'
        m = FancyModel.objects.create(purified=s)
        eq_(m.purified.localized_string_clean,
            '<a href="http://xxx.com" rel="nofollow">yay</a> '
            '<i><a href="http://yyy.com" rel="nofollow">'
            'http://yyy.com</a></i>')
        eq_(m.purified.localized_string, s)

    def test_new_linkified_field(self):
        s = '<a id=xx href="http://xxx.com">yay</a> <i>http://yyy.com</i>'
        m = FancyModel.objects.create(linkified=s)
        eq_(m.linkified.localized_string_clean,
            '<a href="http://xxx.com" rel="nofollow">yay</a> '
            '&lt;i&gt;<a href="http://yyy.com" rel="nofollow">'
            'http://yyy.com</a>&lt;/i&gt;')
        eq_(m.linkified.localized_string, s)

    def test_update_purified_field(self):
        m = FancyModel.objects.get(id=1)
        s = '<a id=xx href="http://xxx.com">yay</a> <i>http://yyy.com</i>'
        m.purified = s
        m.save()
        eq_(m.purified.localized_string_clean,
            '<a href="http://xxx.com" rel="nofollow">yay</a> '
            '<i><a href="http://yyy.com" rel="nofollow">'
            'http://yyy.com</a></i>')
        eq_(m.purified.localized_string, s)

    def test_update_linkified_field(self):
        m = FancyModel.objects.get(id=1)
        s = '<a id=xx href="http://xxx.com">yay</a> <i>http://yyy.com</i>'
        m.linkified = s
        m.save()
        eq_(m.linkified.localized_string_clean,
            '<a href="http://xxx.com" rel="nofollow">yay</a> '
            '&lt;i&gt;<a href="http://yyy.com" rel="nofollow">'
            'http://yyy.com</a>&lt;/i&gt;')
        eq_(m.linkified.localized_string, s)

    def test_purified_field_str(self):
        m = FancyModel.objects.get(id=1)
        eq_(u'%s' % m.purified,
            '<i>x</i> '
            '<a href="http://yyy.com" rel="nofollow">http://yyy.com</a>')

    def test_linkified_field_str(self):
        m = FancyModel.objects.get(id=1)
        eq_(u'%s' % m.linkified,
            '&lt;i&gt;x&lt;/i&gt; '
            '<a href="http://yyy.com" rel="nofollow">http://yyy.com</a>')

    def test_purifed_linkified_fields_in_template(self):
        m = FancyModel.objects.get(id=1)
        env = jinja2.Environment()
        t = env.from_string('{{ m.purified }}=={{ m.linkified }}')
        s = t.render(m=m)
        eq_(s, u'%s==%s' % (m.purified.localized_string_clean,
                            m.linkified.localized_string_clean))


def test_translation_bool():
    t = lambda s: Translation(localized_string=s)

    assert bool(t('text')) is True
    assert bool(t(' ')) is False
    assert bool(t('')) is False
    assert bool(t(None)) is False


def test_widget_value_from_datadict():
    data = {'f_en-US': 'woo', 'f_de': 'herr', 'f_fr_delete': ''}
    actual = widgets.TranslationWidget().value_from_datadict(data, [], 'f')
    expected = {'en-US': 'woo', 'de': 'herr', 'fr': None}
    eq_(actual, expected)


def test_purified_translation_html():
    """__html__() should return a string."""
    x = PurifiedTranslation('<h1>heyhey</h1>')
    assert isinstance(x.__html__(), unicode)
