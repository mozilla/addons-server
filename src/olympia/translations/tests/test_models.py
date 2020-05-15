# -*- coding: utf-8 -*-
import re

import django

from django.conf import settings
from django.db import connections, reset_queries
from django.test import TransactionTestCase
from django.test.utils import override_settings
from django.utils import translation
from django.utils.functional import lazy

import jinja2
import pytest

from unittest.mock import patch
from pyquery import PyQuery as pq

from olympia.amo.models import use_primary_db
from olympia.amo.tests import TestCase
from olympia.translations.hold import translation_saved
from olympia.translations.models import (
    LinkifiedTranslation, NoLinksNoMarkupTranslation,
    PurifiedTranslation, Translation, TranslationSequence)
from olympia.translations.query import order_by_translation
from olympia.translations.tests.testapp.models import (
    ContainsManyToManyToTranslatedModel, ContainsTranslatedThrough,
    FancyModel, TranslatedModel, UntranslatedModel,
    TranslatedModelWithDefaultNull, TranslatedModelLinkedAsForeignKey)


pytestmark = pytest.mark.django_db


def ids(qs):
    return [o.id for o in qs]


class TranslationFixturelessTestCase(TestCase):
    'We want to be able to rollback stuff.'

    def test_whitespace(self):
        t = Translation(localized_string='     khaaaaaan!    ', id=999)
        t.save()
        assert 'khaaaaaan!' == t.localized_string


class TranslationSequenceTestCase(TestCase):
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
        assert TranslationSequence.objects.count() == 0
        for i in range(5):
            newtrans = Translation.new(str(i), 'en-us')
            newtrans.save()
            assert TranslationSequence.objects.count() == 1

    def test_translation_sequence_increases(self):
        """Make sure translation sequence increases monotonically."""
        newtrans1 = Translation.new('abc', 'en-us')
        newtrans1.save()
        newtrans2 = Translation.new('def', 'de')
        newtrans2.save()
        assert newtrans2.pk > newtrans1.pk, (
            'Translation sequence needs to keep increasing.')


class TranslationTestCase(TestCase):
    fixtures = ['testapp/test_models.json']

    def setUp(self):
        super(TranslationTestCase, self).setUp()
        self.redirect_url = settings.REDIRECT_URL
        self.redirect_secret_key = settings.REDIRECT_SECRET_KEY
        settings.REDIRECT_URL = None
        settings.REDIRECT_SECRET_KEY = 'sekrit'
        translation.activate('en-US')

    def tearDown(self):
        settings.REDIRECT_URL = self.redirect_url
        settings.REDIRECT_SECRET_KEY = self.redirect_secret_key
        super(TranslationTestCase, self).tearDown()

    def test_meta_translated_fields(self):
        assert not hasattr(UntranslatedModel._meta, 'translated_fields')

        assert set(TranslatedModel._meta.translated_fields) == (
            set([TranslatedModel._meta.get_field('no_locale'),
                 TranslatedModel._meta.get_field('name'),
                 TranslatedModel._meta.get_field('description')]))

        assert set(FancyModel._meta.translated_fields) == (
            set([FancyModel._meta.get_field('purified'),
                 FancyModel._meta.get_field('linkified')]))

    def test_fetch_translations(self):
        """Basic check of fetching translations in the current locale."""
        o = TranslatedModel.objects.get(pk=1)
        self.trans_eq(o.name, 'some name', 'en-US')
        self.trans_eq(o.description, 'some description', 'en-US')

    def test_fetch_no_translations(self):
        """Make sure models with no translations aren't harmed."""
        o = UntranslatedModel.objects.get(pk=1)
        assert o.number == 17

    def test_fetch_translation_de_locale(self):
        """Check that locale fallbacks work."""
        try:
            translation.activate('de')
            o = TranslatedModel.objects.get(pk=1)
            self.trans_eq(o.name, 'German!! (unst unst)', 'de')
            self.trans_eq(o.description, 'some description', 'en-US')
        finally:
            translation.deactivate()

    def test_create_translation(self):
        assert Translation.objects.count() == 9
        o = TranslatedModel.objects.create(name='english name')

        def get_model():
            return TranslatedModel.objects.get(id=o.id)

        assert Translation.objects.count() == 10
        self.trans_eq(o.name, 'english name', 'en-US')
        assert o.description is None

        # Make sure the translation id is stored on the model, not the autoid.
        assert o.name.id == o.name_id

        # Reload the object from database with a different locale activated.
        # Its name should still be there, using the fallback...
        translation.activate('de')
        german = get_model()
        self.trans_eq(german.name, 'english name', 'en-US')

        # Check that a different locale creates a new row with the same id.
        german.name = u'Gemütlichkeit name'
        german.description = u'clöüserw description'
        german.save()

        assert Translation.objects.count() == 12  # New name *and* description.
        self.trans_eq(german.name, u'Gemütlichkeit name', 'de')
        self.trans_eq(german.description, u'clöüserw description', 'de')

        # ids should be the same, autoids are different.
        assert o.name.id == german.name.id
        assert o.name.autoid != german.name.autoid

        # Check that de finds the right translation.
        fresh_german = get_model()
        self.trans_eq(fresh_german.name, u'Gemütlichkeit name', 'de')
        self.trans_eq(fresh_german.description, u'clöüserw description', 'de')

        # Check that en-US has the right translations.
        translation.deactivate()
        english = get_model()
        self.trans_eq(english.name, 'english name', 'en-US')
        english.debug = True
        assert english.description is None

        english.description = 'english description'
        english.save()

        fresh_english = get_model()
        self.trans_eq(
            fresh_english.description, 'english description', 'en-US')
        assert fresh_english.description.id == fresh_german.description.id

    def test_update_translation(self):
        self.object = TranslatedModel.objects.get(pk=1)
        translation_id = self.object.name.autoid

        self.object.name = 'new name'
        self.object.save()

        self.object = TranslatedModel.objects.get(pk=1)
        self.trans_eq(self.object.name, 'new name', 'en-US')
        # Make sure it was an update, not an insert.
        assert self.object.name.autoid == translation_id

    def test_create_with_dict(self):
        # Set translations with a dict.
        strings = {'en-US': 'right language', 'de': 'wrong language'}
        o = TranslatedModel.objects.create(name=strings)

        # Make sure we get the English text since we're in en-US.
        self.trans_eq(o.name, 'right language', 'en-US')

        # Check that de was set.
        translation.activate('de')
        o = TranslatedModel.objects.get(id=o.id)
        self.trans_eq(o.name, 'wrong language', 'de')

        # We're in de scope, so we should see the de text.
        de = TranslatedModel.objects.create(name=strings)
        self.trans_eq(o.name, 'wrong language', 'de')

        # Make sure en-US was still set.
        translation.deactivate()
        o = TranslatedModel.objects.get(id=de.id)
        self.trans_eq(o.name, 'right language', 'en-US')

    def test_update_with_dict(self):
        def get_model():
            return TranslatedModel.objects.get(pk=self.object.pk)

        # There's existing en-US and de strings.
        strings = {'de': None, 'fr': 'oui'}

        # Don't try checking that the model's name value is en-US.  It will be
        # one of the other locales, but we don't know which one.  You just set
        # the name to a dict, deal with it.
        self.object = TranslatedModel.objects.create(name='some name')
        self.object.name = strings
        self.object.save()

        # en-US was not touched.
        self.trans_eq(get_model().name, 'some name', 'en-US')

        # de was updated to NULL, so it falls back to en-US.
        translation.activate('de')
        self.trans_eq(get_model().name, 'some name', 'en-US')

        # fr was added.
        translation.activate('fr')
        self.trans_eq(get_model().name, 'oui', 'fr')

    def test_signal_is_sent(self):
        self.call_count = 0

        def handler(**kw):
            self.call_count += 1
            assert kw.get('instance') == self.object
            assert kw.get('sender') == TranslatedModel
            assert kw.get('field_name') == 'name'

        translation_saved.connect(handler)
        self.test_update_translation()
        translation_saved.disconnect(handler)

        assert self.call_count == 1

    def test_signal_is_sent_with_dict(self):
        self.call_count = 0
        self.handler_instance = None

        def handler(**kw):
            self.call_count += 1
            assert kw.get('sender') == TranslatedModel
            self.handler_instance = kw.get('instance')
            assert kw.get('field_name') == 'name'

        translation_saved.connect(handler)
        self.test_update_with_dict()
        translation_saved.disconnect(handler)

        assert self.call_count == 3
        assert self.handler_instance == self.object  # Set by handler()

    def test_dict_bad_locale(self):
        m = TranslatedModel.objects.get(pk=1)
        m.name = {'de': 'oof', 'xxx': 'bam', 'es': 'si'}
        m.save()

        ts = Translation.objects.filter(id=m.name_id)
        assert sorted(ts.values_list('locale', flat=True)) == (
            ['de', 'en-US', 'es'])

    def test_sorting(self):
        """Test translation comparisons in Python code."""
        b = Translation.new('bbbb', 'de')
        a = Translation.new('aaaa', 'de')
        c = Translation.new('cccc', 'de')
        assert sorted([c, a, b]) == [a, b, c]

    def test_sorting_en(self):
        query = TranslatedModel.objects.all()
        expected = [4, 1, 3]
        assert ids(order_by_translation(query, 'name')) == expected
        assert ids(order_by_translation(query, '-name')) == (
            list(reversed(expected)))

    def test_order_by_translations_query_uses_left_outer_join(self):
        translation.activate('de')
        qs = TranslatedModel.objects.all()
        query = str(order_by_translation(qs, 'name').query)
        # There should be 2 LEFT OUTER JOIN to find translations matching
        # current language and fallback.
        joins = re.findall('LEFT OUTER JOIN `translations`', query)
        assert len(joins) == 2

    def test_sorting_mixed(self):
        translation.activate('de')
        q = TranslatedModel.objects.all()
        expected = [1, 4, 3]

        assert ids(order_by_translation(q, 'name')) == expected
        assert ids(order_by_translation(q, '-name')) == (
            list(reversed(expected)))

    def test_sorting_by_field(self):
        field = TranslatedModel._meta.get_field('default_locale')
        fallback = classmethod(lambda cls: field)
        with patch.object(TranslatedModel, 'get_fallback',
                          fallback, create=True):
            translation.activate('de')
            qs = TranslatedModel.objects.all()
            expected = [3, 1, 4]

            assert ids(order_by_translation(qs, 'name')) == expected
            assert ids(order_by_translation(qs, '-name')) == (
                list(reversed(expected)))

    def test_sorting_by_field_with_related_model(self):
        # This time we sort a "regular" queryset through a relation that
        # contains a translated field.
        container = ContainsManyToManyToTranslatedModel.objects.create()
        to_one = ContainsTranslatedThrough.objects.create(
            container=container, target=TranslatedModel.objects.get(pk=1))
        to_three = ContainsTranslatedThrough.objects.create(
            container=container, target=TranslatedModel.objects.get(pk=3))
        to_four = ContainsTranslatedThrough.objects.create(
            container=container, target=TranslatedModel.objects.get(pk=4))

        # We also add another TranslatedModel object that doesn't have a
        # translation in 'en-US' or 'de'.
        translation.activate('fr')
        five = TranslatedModel.objects.create(
            default_locale='fr', name='a français')
        to_five = ContainsTranslatedThrough.objects.create(
            container=container, target=five)

        def get_queryset():
            # FIXME: We force a join with TranslatedModel, because otherwise
            # order_by_translation isn't smart enough to do it itself.
            return ContainsTranslatedThrough.objects.filter(
                target__name_id__gt=0)

        # First, no fallback. The "five" instance is absent, because there is
        # no translation matching 'de' or settings.LANGUAGE_CODE (en-US).
        translation.activate('de')
        qs = get_queryset()
        expected = [to_one.pk, to_four.pk, to_three.pk]

        assert ids(
            order_by_translation(qs, 'name', TranslatedModel)) == expected
        assert ids(order_by_translation(qs, '-name', TranslatedModel)) == (
            list(reversed(expected)))

        # Second, with fallback. This changes what translations are available,
        # causing "to_five" to be found, and "to_three" to be higher, because
        # we pick up its translation matching their default_locale.
        field = TranslatedModel._meta.get_field('default_locale')
        fallback = classmethod(lambda cls: field)
        with patch.object(TranslatedModel, 'get_fallback',
                          fallback, create=True):
            qs = get_queryset()
            expected = [to_five.pk, to_three.pk, to_one.pk, to_four.pk]
            assert ids(
                order_by_translation(qs, 'name', TranslatedModel)) == expected
            assert ids(order_by_translation(qs, '-name', TranslatedModel)) == (
                list(reversed(expected)))

    def test_new_purified_field(self):
        # This is not a full test of the html sanitizing.  We expect the
        # underlying bleach library to have full tests.
        s = '<a id=xx href="http://xxx.com">yay</a> <i>http://yyy.com</i>'
        m = FancyModel.objects.create(purified=s)

        doc = pq(m.purified.localized_string_clean)
        assert doc('a[href="http://xxx.com"][rel="nofollow"]')[0].text == 'yay'
        assert doc('a[href="http://yyy.com"][rel="nofollow"]')[0].text == (
            'http://yyy.com')
        assert m.purified.localized_string == s

    def test_new_linkified_field(self):
        s = '<a id=xx href="http://xxx.com">yay</a> <i>http://yyy.com</i>'
        m = FancyModel.objects.create(linkified=s)

        doc = pq(m.linkified.localized_string_clean)
        assert doc('a[href="http://xxx.com"][rel="nofollow"]')[0].text == 'yay'
        assert doc('a[href="http://yyy.com"][rel="nofollow"]')[0].text == (
            'http://yyy.com')
        assert not doc('i')
        assert '&lt;i&gt;' in m.linkified.localized_string_clean
        assert m.linkified.localized_string == s

    def test_update_purified_field(self):
        m = FancyModel.objects.get(pk=1)
        s = '<a id=xx href="http://xxx.com">yay</a> <i>http://yyy.com</i>'
        m.purified = s
        m.save()

        doc = pq(m.purified.localized_string_clean)
        assert doc('a[href="http://xxx.com"][rel="nofollow"]')[0].text == 'yay'
        assert doc('a[href="http://yyy.com"][rel="nofollow"]')[0].text == (
            'http://yyy.com')
        assert m.purified.localized_string == s

    def test_update_linkified_field(self):
        m = FancyModel.objects.get(pk=1)
        s = '<a id=xx href="http://xxx.com">yay</a> <i>http://yyy.com</i>'
        m.linkified = s
        m.save()

        doc = pq(m.linkified.localized_string_clean)
        assert doc('a[href="http://xxx.com"][rel="nofollow"]')[0].text == 'yay'
        assert doc('a[href="http://yyy.com"][rel="nofollow"]')[0].text == (
            'http://yyy.com')
        assert '&lt;i&gt;' in m.linkified.localized_string_clean
        assert m.linkified.localized_string == s

    def test_purified_field_str(self):
        m = FancyModel.objects.get(pk=1)
        stringified = u'%s' % m.purified

        doc = pq(stringified)
        assert doc('a[href="http://yyy.com"][rel="nofollow"]')[0].text == (
            'http://yyy.com')
        assert doc('i')[0].text == 'x'

    def test_linkified_field_str(self):
        m = FancyModel.objects.get(pk=1)
        stringified = u'%s' % m.linkified

        doc = pq(stringified)
        assert doc('a[href="http://yyy.com"][rel="nofollow"]')[0].text == (
            'http://yyy.com')
        assert not doc('i')
        assert '&lt;i&gt;' in stringified

    def test_purifed_linkified_fields_in_template(self):
        m = FancyModel.objects.get(pk=1)
        env = jinja2.Environment()
        t = env.from_string('{{ m.purified }}=={{ m.linkified }}')
        s = t.render({'m': m})
        assert s == u'%s==%s' % (m.purified.localized_string_clean,
                                 m.linkified.localized_string_clean)

    def test_outgoing_url(self):
        """
        Make sure linkified field is properly bounced off our outgoing URL
        redirector.
        """
        s = 'I like http://example.org/awesomepage.html .'
        with self.settings(REDIRECT_URL='http://example.com/'):
            m = FancyModel.objects.create(linkified=s)
            """
            assert m.linkified.localized_string_clean == (
                'I like <a rel="nofollow" href="http://example.com/'
                '40979175e3ef6d7a9081085f3b99f2f05447b22ba790130517dd62b7ee59ef94/'
                'http%3A//example.org/'
                'awesomepage.html">http://example.org/awesomepage'
                '.html</a> .')
            """
            doc = pq(m.linkified.localized_string_clean)
            link = doc('a')[0]
            assert link.attrib['href'] == (
                'http://example.com/40979175e3ef6d7a9081085f3b99f2f05447b22ba7'
                '90130517dd62b7ee59ef94/http%3A//example.org/awesomepage.html')
            assert link.attrib['rel'] == 'nofollow'
            assert link.text == 'http://example.org/awesomepage.html'
            assert m.linkified.localized_string == s

    def test_require_locale(self):
        obj = TranslatedModel.objects.get(pk=1)
        assert str(obj.no_locale) == 'blammo'
        assert obj.no_locale.locale == 'en-US'

        # Switch the translation to a locale we wouldn't pick up by default.
        obj.no_locale.locale = 'fr'
        obj.no_locale.save()

        obj = TranslatedModel.objects.get(pk=1)
        assert str(obj.no_locale) == 'blammo'
        assert obj.no_locale.locale == 'fr'

    def test_delete_set_null(self):
        """
        Test that deleting a translation sets the corresponding FK to NULL,
        if it was the only translation for this field.
        """
        obj = TranslatedModel.objects.get(pk=1)
        trans_id = obj.description.id
        assert Translation.objects.filter(id=trans_id).count() == 1

        obj.description.delete()

        obj = TranslatedModel.objects.get(pk=1)
        assert obj.description_id is None
        assert obj.description is None
        assert not Translation.objects.filter(id=trans_id).exists()

    @patch.object(TranslatedModel, 'get_fallback', create=True)
    def test_delete_keep_other_translations(self, get_fallback):
        # To make sure both translations for the name are used, set the
        # fallback to the second locale, which is 'de'.
        get_fallback.return_value = 'de'

        obj = TranslatedModel.objects.get(pk=1)

        orig_name_id = obj.name.id
        assert obj.name.locale.lower() == 'en-us'
        assert Translation.objects.filter(id=orig_name_id).count() == 2

        obj.name.delete()

        obj = TranslatedModel.objects.get(pk=1)
        assert Translation.objects.filter(id=orig_name_id).count() == 1

        # We shouldn't have set name_id to None.
        assert obj.name_id == orig_name_id

        # We should find a Translation.
        assert obj.name.id == orig_name_id
        assert obj.name.locale == 'de'


class TranslationMultiDbTests(TransactionTestCase):
    fixtures = ['testapp/test_models.json']

    def setUp(self):
        super(TranslationMultiDbTests, self).setUp()
        translation.activate('en-US')

    def tearDown(self):
        self.cleanup_fake_connections()
        super(TranslationMultiDbTests, self).tearDown()

    def reset_queries(self):
        # Django does a separate SQL query once per connection on MySQL, see
        # https://code.djangoproject.com/ticket/16809 ; This pollutes the
        # queries counts, so we initialize a connection cursor early ourselves
        # before resetting queries to avoid this. It also does a query once for
        # the MySQL version and then stores it into a cached_property, so do
        # that early as well.
        for con in django.db.connections:
            connections[con].cursor()
            connections[con].mysql_version
        reset_queries()

    @property
    def mocked_dbs(self):
        return {
            'default': settings.DATABASES['default'],
            'slave-1': settings.DATABASES['default'].copy(),
            'slave-2': settings.DATABASES['default'].copy(),
        }

    def cleanup_fake_connections(self):
        with patch.object(django.db.connections, 'databases', self.mocked_dbs):
            for key in ('default', 'slave-1', 'slave-2'):
                connections[key].close()

    @override_settings(DEBUG=True)
    def test_translations_queries(self):
        # Make sure we are in a clean environnement.
        self.reset_queries()
        TranslatedModel.objects.get(pk=1)
        assert len(connections['default'].queries) == 2

    @override_settings(DEBUG=True)
    @patch('multidb.get_replica', lambda: 'slave-2')
    def test_translations_reading_from_multiple_db(self):
        with patch.object(django.db.connections, 'databases', self.mocked_dbs):
            # Make sure we are in a clean environnement.
            self.reset_queries()

            TranslatedModel.objects.get(pk=1)
            assert len(connections['default'].queries) == 0
            assert len(connections['slave-1'].queries) == 0
            assert len(connections['slave-2'].queries) == 2

    @override_settings(DEBUG=True)
    @patch('multidb.get_replica', lambda: 'slave-2')
    @pytest.mark.xfail(reason='Needs django-queryset-transform patch to work')
    def test_translations_reading_from_multiple_db_using(self):
        with patch.object(django.db.connections, 'databases', self.mocked_dbs):
            # Make sure we are in a clean environnement.
            self.reset_queries()

            TranslatedModel.objects.using('slave-1').get(pk=1)
            assert len(connections['default'].queries) == 0
            assert len(connections['slave-1'].queries) == 2
            assert len(connections['slave-2'].queries) == 0

    @override_settings(DEBUG=True)
    @patch('multidb.get_replica', lambda: 'slave-2')
    def test_translations_reading_from_multiple_db_pinning(self):
        with patch.object(django.db.connections, 'databases', self.mocked_dbs):
            # Make sure we are in a clean environnement.
            self.reset_queries()

            with use_primary_db():
                TranslatedModel.objects.get(pk=1)
                assert len(connections['default'].queries) == 2
                assert len(connections['slave-1'].queries) == 0
                assert len(connections['slave-2'].queries) == 0


class PurifiedTranslationTest(TestCase):

    def test_output(self):
        assert isinstance(PurifiedTranslation().__html__(), str)

    def test_raw_text(self):
        s = u'   This is some text   '
        x = PurifiedTranslation(localized_string=s)
        assert x.__html__() == 'This is some text'

    def test_allowed_tags(self):
        s = u'<b>bold text</b> or <code>code</code>'
        x = PurifiedTranslation(localized_string=s)
        assert x.__html__() == u'<b>bold text</b> or <code>code</code>'

    def test_forbidden_tags(self):
        s = u'<script>some naughty xss</script>'
        x = PurifiedTranslation(localized_string=s)
        assert x.__html__() == '&lt;script&gt;some naughty xss&lt;/script&gt;'

    def test_internal_link(self):
        s = u'<b>markup</b> <a href="http://addons.mozilla.org/foo">bar</a>'
        x = PurifiedTranslation(localized_string=s)
        doc = pq(x.__html__())
        links = doc('a[href="http://addons.mozilla.org/foo"][rel="nofollow"]')
        assert links[0].text == 'bar'
        assert doc('b')[0].text == 'markup'

    @patch('olympia.amo.urlresolvers.get_outgoing_url')
    def test_external_link(self, get_outgoing_url_mock):
        get_outgoing_url_mock.return_value = 'http://external.url'
        s = u'<b>markup</b> <a href="http://example.com">bar</a>'
        x = PurifiedTranslation(localized_string=s)
        doc = pq(x.__html__())
        links = doc('a[href="http://external.url"][rel="nofollow"]')
        assert links[0].text == 'bar'
        assert doc('b')[0].text == 'markup'

    @patch('olympia.amo.urlresolvers.get_outgoing_url')
    def test_external_text_link(self, get_outgoing_url_mock):
        get_outgoing_url_mock.return_value = 'http://external.url'
        s = u'<b>markup</b> http://example.com'
        x = PurifiedTranslation(localized_string=s)
        doc = pq(x.__html__())
        links = doc('a[href="http://external.url"][rel="nofollow"]')
        assert links[0].text == 'http://example.com'
        assert doc('b')[0].text == 'markup'


class LinkifiedTranslationTest(TestCase):

    @patch('olympia.amo.urlresolvers.get_outgoing_url')
    def test_allowed_tags(self, get_outgoing_url_mock):
        get_outgoing_url_mock.return_value = 'http://external.url'
        s = u'<a href="http://example.com">bar</a>'
        x = LinkifiedTranslation(localized_string=s)
        doc = pq(x.__html__())
        links = doc('a[href="http://external.url"][rel="nofollow"]')
        assert links[0].text == 'bar'

    def test_forbidden_tags(self):
        s = u'<script>some naughty xss</script> <b>bold</b>'
        x = LinkifiedTranslation(localized_string=s)
        assert x.__html__() == (
            '&lt;script&gt;some naughty xss&lt;/script&gt; '
            '&lt;b&gt;bold&lt;/b&gt;')


class NoLinksNoMarkupTranslationTest(TestCase):

    def test_forbidden_tags(self):
        s = u'<script>some naughty xss</script> <b>bold</b>'
        x = NoLinksNoMarkupTranslation(localized_string=s)
        assert x.__html__() == (
            '&lt;script&gt;some naughty xss&lt;/script&gt; '
            '&lt;b&gt;bold&lt;/b&gt;')

    def test_links_stripped(self):
        # Link with markup.
        s = u'a <a href="http://example.com">link</a> with markup'
        x = NoLinksNoMarkupTranslation(localized_string=s)
        assert x.__html__() == u'a  with markup'

        # Text link.
        s = u'a text http://example.com link'
        x = NoLinksNoMarkupTranslation(localized_string=s)
        assert x.__html__() == u'a text  link'

        # Text link, markup link, forbidden tags and bad markup.
        s = (u'a <a href="http://example.com">link</a> with markup, a text '
             u'http://example.com link, <b>with forbidden tags</b>, '
             u'<script>forbidden tags</script> and <http://bad.markup.com')
        x = NoLinksNoMarkupTranslation(localized_string=s)
        assert x.__html__() == (
            u'a  with markup, a text  link, '
            u'&lt;b&gt;with forbidden tags&lt;/b&gt;, '
            u'&lt;script&gt;forbidden tags&lt;/script&gt; and')


def test_translation_bool():
    def translation(s):
        return Translation(localized_string=s)

    assert bool(translation('text')) is True
    assert bool(translation(' ')) is False
    assert bool(translation('')) is False
    assert bool(translation(None)) is False


def test_translation_unicode():
    def translation(s):
        return Translation(localized_string=s)

    assert str(translation('hello')) == 'hello'
    assert str(translation(None)) == ''


def test_comparison_with_lazy():
    lazy_u = lazy(lambda s: s, str)
    Translation(localized_string='xxx') == lazy_u('xxx')
    lazy_u('xxx') == Translation(localized_string='xxx')


def test_translated_field_default_null():
    assert Translation.objects.count() == 0
    obj = TranslatedModelWithDefaultNull.objects.create(name='english name')

    def get_model():
        return TranslatedModelWithDefaultNull.objects.get(pk=obj.pk)

    assert Translation.objects.count() == 1

    # Make sure the translation id is stored on the model, not the autoid.
    assert obj.name.id == obj.name_id

    # Reload the object from database with a different locale activated.
    # Its name should still be there, using the fallback...
    translation.activate('de')
    german = get_model()
    assert german.name == 'english name'
    assert german.name.locale == 'en-us'

    # Check that a different locale creates a new row with the same id.
    german.name = u'Gemütlichkeit name'
    german.save()

    assert Translation.objects.count() == 2  # New name *and* description.
    assert german.name == u'Gemütlichkeit name'
    assert german.name.locale == 'de'

    # ids should be the same, autoids are different.
    assert obj.name.id == german.name.id
    assert obj.name.autoid != german.name.autoid

    # Check that de finds the right translation.
    fresh_german = get_model()
    assert fresh_german.name == u'Gemütlichkeit name'

    # Update!
    translation.activate('en-us')
    obj = TranslatedModelWithDefaultNull.objects.get(pk=obj.pk)
    translation_id = obj.name.autoid

    obj.name = 'new name'
    obj.save()

    obj = TranslatedModelWithDefaultNull.objects.get(pk=obj.pk)
    assert obj.name == 'new name'
    assert obj.name.locale == 'en-us'
    # Make sure it was an update, not an insert.
    assert obj.name.autoid == translation_id

    # Set translations with a dict.
    strings = {'en-us': 'right language', 'de': 'wrong language'}
    obj = TranslatedModelWithDefaultNull.objects.create(name=strings)

    # Make sure we get the English text since we're in en-US.
    assert obj.name == 'right language'

    # Check that de was set.
    translation.activate('de')
    obj = TranslatedModelWithDefaultNull.objects.get(pk=obj.pk)
    assert obj.name == 'wrong language'
    assert obj.name.locale == 'de'


def test_translated_field_fk_lookups():
    """
    Test that translations are properly resolved even through models
    that are one foreign-key layer away
    (e.g Version -> License -> Translation).

    The problem here was, that we did not set `base_manager_name` on
    the `ModelBase`. This superseeded setting `use_for_related_fields`.
    """
    assert Translation.objects.count() == 0
    assert TranslatedModelLinkedAsForeignKey.objects.count() == 0
    obj = TranslatedModelLinkedAsForeignKey.objects.create(name='english name')

    def get_model():
        return TranslatedModelLinkedAsForeignKey.objects.get(pk=obj.pk)

    assert Translation.objects.count() == 1

    # Make sure the translation id is stored on the model, not the autoid.
    assert obj.name.id == obj.name_id

    # Reload the object from database with a different locale activated.
    # Its name should still be there, using the fallback...
    translation.activate('de')
    german = get_model()
    assert german.name == 'english name'
    assert german.name.locale == 'en-us'

    # Check that a different locale creates a new row with the same id.
    german.name = u'Gemütlichkeit name'
    german.save()

    assert Translation.objects.count() == 2  # New name *and* description.
    assert german.name == u'Gemütlichkeit name'
    assert german.name.locale == 'de'

    # Now fetch the parent `TranslatedModel` and make sure that
    # all the relevant translations from `TranslatedModelLinkedAsForeignKey`
    # are properly loaded.
    parent = TranslatedModel.objects.create(name='parent')
    parent.translated_through_fk = obj
    parent.save()

    # This still works, simply attaching the model
    assert parent.translated_through_fk.name_id == obj.name_id
    assert parent.translated_through_fk.name is not None

    # Now make sure that the translation is properly set when fetching
    # the object
    fresh_parent = TranslatedModel.objects.get(pk=parent.pk)
    assert fresh_parent.translated_through_fk.name_id == obj.name_id
    assert fresh_parent.translated_through_fk.name is not None


def test_translated_field_emoji_support():
    # Make sure utf8mb4 settings are correct and emojis are correctly handled
    assert Translation.objects.count() == 0
    obj = TranslatedModel.objects.create(name=u'😀❤')

    def get_model():
        return TranslatedModel.objects.get(pk=obj.pk)

    assert Translation.objects.count() == 1

    # Make sure the translation id is stored on the model, not the autoid.
    assert obj.name.id == obj.name_id

    # Reload the object from database with a different locale activated.
    # Its name should still be there, using the fallback...
    translation.activate('de')
    german = get_model()
    assert german.name == u'😀❤'
    assert german.name.locale == 'en-us'

    # Check that a different locale creates a new row with the same id.
    german.name = u'😀'
    german.save()

    assert Translation.objects.count() == 2  # New name *and* description.
    assert german.name == u'😀'
    assert german.name.locale == 'de'

    # ids should be the same, autoids are different.
    assert obj.name.id == german.name.id
    assert obj.name.autoid != german.name.autoid

    # Check that de finds the right translation.
    fresh_german = get_model()
    assert fresh_german.name == u'😀'
