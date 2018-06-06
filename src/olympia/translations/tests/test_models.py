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
import multidb
import pytest

from mock import patch
from pyquery import PyQuery as pq

from olympia.amo.tests import BaseTestCase
from olympia.translations import widgets
from olympia.translations.models import (
    LinkifiedTranslation, NoLinksNoMarkupTranslation, NoLinksTranslation,
    PurifiedTranslation, Translation, TranslationSequence)
from olympia.translations.query import order_by_translation
from olympia.translations.tests.testapp.models import (
    FancyModel, TranslatedModel, UntranslatedModel)


pytestmark = pytest.mark.django_db


def ids(qs):
    return [o.id for o in qs]


class TranslationFixturelessTestCase(BaseTestCase):
    "We want to be able to rollback stuff."

    def test_whitespace(self):
        t = Translation(localized_string='     khaaaaaan!    ', id=999)
        t.save()
        assert 'khaaaaaan!' == t.localized_string


class TranslationSequenceTestCase(BaseTestCase):
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


class TranslationTestCase(BaseTestCase):
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
        o = TranslatedModel.objects.get(id=1)
        self.trans_eq(o.name, 'some name', 'en-US')
        self.trans_eq(o.description, 'some description', 'en-US')

    def test_fetch_no_translations(self):
        """Make sure models with no translations aren't harmed."""
        o = UntranslatedModel.objects.get(id=1)
        assert o.number == 17

    def test_fetch_translation_de_locale(self):
        """Check that locale fallbacks work."""
        try:
            translation.activate('de')
            o = TranslatedModel.objects.get(id=1)
            self.trans_eq(o.name, 'German!! (unst unst)', 'de')
            self.trans_eq(o.description, 'some description', 'en-US')
        finally:
            translation.deactivate()

    def test_create_translation(self):
        o = TranslatedModel.objects.create(name='english name')

        def get_model():
            return TranslatedModel.objects.get(id=o.id)

        self.trans_eq(o.name, 'english name', 'en-US')
        assert o.description is None

        # Make sure the translation id is stored on the model, not the autoid.
        assert o.name.id == o.name_id

        # Check that a different locale creates a new row with the same id.
        translation.activate('de')
        german = get_model()
        self.trans_eq(o.name, 'english name', 'en-US')

        german.name = u'Gemütlichkeit name'
        german.description = u'clöüserw description'
        german.save()

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
        o = TranslatedModel.objects.get(id=1)
        translation_id = o.name.autoid

        o.name = 'new name'
        o.save()

        o = TranslatedModel.objects.get(id=1)
        self.trans_eq(o.name, 'new name', 'en-US')
        # Make sure it was an update, not an insert.
        assert o.name.autoid == translation_id

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
            return TranslatedModel.objects.get(id=1)

        # There's existing en-US and de strings.
        strings = {'de': None, 'fr': 'oui'}

        # Don't try checking that the model's name value is en-US.  It will be
        # one of the other locales, but we don't know which one.  You just set
        # the name to a dict, deal with it.
        m = get_model()
        m.name = strings
        m.save()

        # en-US was not touched.
        self.trans_eq(get_model().name, 'some name', 'en-US')

        # de was updated to NULL, so it falls back to en-US.
        translation.activate('de')
        self.trans_eq(get_model().name, 'some name', 'en-US')

        # fr was added.
        translation.activate('fr')
        self.trans_eq(get_model().name, 'oui', 'fr')

    def test_dict_bad_locale(self):
        m = TranslatedModel.objects.get(id=1)
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
        q = TranslatedModel.objects.all()
        expected = [4, 1, 3]

        assert ids(order_by_translation(q, 'name')) == expected
        assert ids(order_by_translation(q, '-name')) == (
            list(reversed(expected)))

    def test_order_by_translations_query_uses_left_outer_join(self):
        translation.activate('de')
        qs = TranslatedModel.objects.all()
        query = unicode(order_by_translation(qs, 'name').query)
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
        m = FancyModel.objects.get(id=1)
        s = '<a id=xx href="http://xxx.com">yay</a> <i>http://yyy.com</i>'
        m.purified = s
        m.save()

        doc = pq(m.purified.localized_string_clean)
        assert doc('a[href="http://xxx.com"][rel="nofollow"]')[0].text == 'yay'
        assert doc('a[href="http://yyy.com"][rel="nofollow"]')[0].text == (
            'http://yyy.com')
        assert m.purified.localized_string == s

    def test_update_linkified_field(self):
        m = FancyModel.objects.get(id=1)
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
        m = FancyModel.objects.get(id=1)
        stringified = u'%s' % m.purified

        doc = pq(stringified)
        assert doc('a[href="http://yyy.com"][rel="nofollow"]')[0].text == (
            'http://yyy.com')
        assert doc('i')[0].text == 'x'

    def test_linkified_field_str(self):
        m = FancyModel.objects.get(id=1)
        stringified = u'%s' % m.linkified

        doc = pq(stringified)
        assert doc('a[href="http://yyy.com"][rel="nofollow"]')[0].text == (
            'http://yyy.com')
        assert not doc('i')
        assert '&lt;i&gt;' in stringified

    def test_purifed_linkified_fields_in_template(self):
        m = FancyModel.objects.get(id=1)
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
                "http://example.com/40979175e3ef6d7a9081085f3b99f2f05447b22ba7"
                "90130517dd62b7ee59ef94/http%3A//example.org/awesomepage.html")
            assert link.attrib['rel'] == "nofollow"
            assert link.text == "http://example.org/awesomepage.html"
            assert m.linkified.localized_string == s

    def test_require_locale(self):
        obj = TranslatedModel.objects.get(id=1)
        assert unicode(obj.no_locale) == 'blammo'
        assert obj.no_locale.locale == 'en-US'

        # Switch the translation to a locale we wouldn't pick up by default.
        obj.no_locale.locale = 'fr'
        obj.no_locale.save()

        obj = TranslatedModel.objects.get(id=1)
        assert unicode(obj.no_locale) == 'blammo'
        assert obj.no_locale.locale == 'fr'

    def test_delete_set_null(self):
        """
        Test that deleting a translation sets the corresponding FK to NULL,
        if it was the only translation for this field.
        """
        obj = TranslatedModel.objects.get(id=1)
        trans_id = obj.description.id
        assert Translation.objects.filter(id=trans_id).count() == 1

        obj.description.delete()

        obj = TranslatedModel.objects.get(id=1)
        assert obj.description_id is None
        assert obj.description is None
        assert not Translation.objects.filter(id=trans_id).exists()

    @patch.object(TranslatedModel, 'get_fallback', create=True)
    def test_delete_keep_other_translations(self, get_fallback):
        # To make sure both translations for the name are used, set the
        # fallback to the second locale, which is 'de'.
        get_fallback.return_value = 'de'

        obj = TranslatedModel.objects.get(id=1)

        orig_name_id = obj.name.id
        assert obj.name.locale.lower() == 'en-us'
        assert Translation.objects.filter(id=orig_name_id).count() == 2

        obj.name.delete()

        obj = TranslatedModel.objects.get(id=1)
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
        # before resetting queries to avoid this.
        for con in django.db.connections:
            connections[con].cursor()
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
    @patch('multidb.get_slave', lambda: 'slave-2')
    def test_translations_reading_from_multiple_db(self):
        with patch.object(django.db.connections, 'databases', self.mocked_dbs):
            # Make sure we are in a clean environnement.
            self.reset_queries()

            TranslatedModel.objects.get(pk=1)
            assert len(connections['default'].queries) == 0
            assert len(connections['slave-1'].queries) == 0
            assert len(connections['slave-2'].queries) == 2

    @override_settings(DEBUG=True)
    @patch('multidb.get_slave', lambda: 'slave-2')
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
    @patch('multidb.get_slave', lambda: 'slave-2')
    def test_translations_reading_from_multiple_db_pinning(self):
        with patch.object(django.db.connections, 'databases', self.mocked_dbs):
            # Make sure we are in a clean environnement.
            self.reset_queries()

            with multidb.pinning.use_master:
                TranslatedModel.objects.get(pk=1)
                assert len(connections['default'].queries) == 2
                assert len(connections['slave-1'].queries) == 0
                assert len(connections['slave-2'].queries) == 0


class PurifiedTranslationTest(BaseTestCase):

    def test_output(self):
        assert isinstance(PurifiedTranslation().__html__(), unicode)

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


class LinkifiedTranslationTest(BaseTestCase):

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


class NoLinksTranslationTest(BaseTestCase):

    def test_allowed_tags(self):
        s = u'<b>bold text</b> or <code>code</code>'
        x = NoLinksTranslation(localized_string=s)
        assert x.__html__() == u'<b>bold text</b> or <code>code</code>'

    def test_forbidden_tags(self):
        s = u'<script>some naughty xss</script>'
        x = NoLinksTranslation(localized_string=s)
        assert x.__html__() == '&lt;script&gt;some naughty xss&lt;/script&gt;'

    def test_links_stripped(self):
        # Link with markup.
        s = u'a <a href="http://example.com">link</a> with markup'
        x = NoLinksTranslation(localized_string=s)
        assert x.__html__() == u'a  with markup'

        # Text link.
        s = u'a text http://example.com link'
        x = NoLinksTranslation(localized_string=s)
        assert x.__html__() == u'a text  link'

        # Text link, markup link, allowed tags, forbidden tags and bad markup.
        s = (u'a <a href="http://example.com">link</a> with markup, a text '
             u'http://example.com link, <b>with allowed tags</b>, '
             u'<script>forbidden tags</script> and <http://bad.markup.com')
        x = NoLinksTranslation(localized_string=s)
        assert x.__html__() == (
            u'a  with markup, a text  link, '
            u'<b>with allowed tags</b>, '
            u'&lt;script&gt;forbidden tags&lt;/script&gt; and')


class NoLinksNoMarkupTranslationTest(BaseTestCase):

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
    def t(s):
        return Translation(localized_string=s)

    assert bool(t('text')) is True
    assert bool(t(' ')) is False
    assert bool(t('')) is False
    assert bool(t(None)) is False


def test_translation_unicode():
    def t(s):
        return Translation(localized_string=s)

    assert unicode(t('hello')) == 'hello'
    assert unicode(t(None)) == ''


def test_widget_value_from_datadict():
    data = {'f_en-US': 'woo', 'f_de': 'herr', 'f_fr_delete': ''}
    actual = widgets.TransMulti().value_from_datadict(data, [], 'f')
    expected = {'en-US': 'woo', 'de': 'herr', 'fr': None}
    assert actual == expected


def test_comparison_with_lazy():
    x = Translation(localized_string='xxx')
    lazy_u = lazy(lambda x: x, unicode)
    x == lazy_u('xxx')
    lazy_u('xxx') == x
