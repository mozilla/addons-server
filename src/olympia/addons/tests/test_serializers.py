# -*- coding: utf-8 -*-
from datetime import datetime

from elasticsearch_dsl import Search
from rest_framework.test import APIRequestFactory

from olympia import amo
from olympia.amo.helpers import absolutify
from olympia.amo.tests import addon_factory, ESTestCase, TestCase, user_factory
from olympia.amo.urlresolvers import reverse
from olympia.addons.indexers import AddonIndexer
from olympia.addons.models import Addon, AddonUser, Persona, Preview
from olympia.addons.serializers import AddonSerializer, ESAddonSerializer
from olympia.addons.utils import generate_addon_guid


class AddonSerializerOutputTestMixin(object):
    """Mixin containing tests to execute on both the regular and the ES Addon
    serializer."""
    def setUp(self):
        self.request = APIRequestFactory().get('/')

    def test_basic(self):
        self.addon = addon_factory(
            average_rating=4.21,
            description=u'My Addôn description',
            file_kw={
                'hash': 'fakehash',
                'platform': amo.PLATFORM_WIN.id,
                'size': 42,
            },
            guid=generate_addon_guid(),
            homepage=u'https://www.example.org/',
            icon_type='image/png',
            name=u'My Addôn',
            public_stats=True,
            slug='my-addon',
            summary=u'My Addôn summary',
            support_email=u'support@example.org',
            support_url=u'https://support.example.org/support/my-addon/',
            tags=['some_tag', 'some_other_tag'],
            total_reviews=666,
        )
        AddonUser.objects.create(user=user_factory(username='hidden_author'),
                                 addon=self.addon, listed=False)
        second_author = user_factory(
            username='second_author', display_name=u'Secönd Author')
        first_author = user_factory(
            username='first_author', display_name=u'First Authôr')
        AddonUser.objects.create(
            user=second_author, addon=self.addon, position=2)
        AddonUser.objects.create(
            user=first_author, addon=self.addon, position=1)
        second_preview = Preview.objects.create(
            addon=self.addon, position=2,
            caption={'en-US': u'My câption', 'fr': u'Mön tîtré'})
        first_preview = Preview.objects.create(addon=self.addon, position=1)

        result = self.serialize()
        version = self.addon.current_version
        file_ = version.files.latest('pk')

        assert result['id'] == self.addon.pk

        assert result['current_version']
        assert result['current_version']['id'] == version.pk
        assert result['current_version']['compatibility'] == {
            'firefox': {'max': u'5.0.99', 'min': u'4.0.99'}
        }
        assert result['current_version']['files']
        assert len(result['current_version']['files']) == 1

        result_file = result['current_version']['files'][0]
        assert result_file['id'] == file_.pk
        assert result_file['created'] == file_.created.isoformat()
        assert result_file['hash'] == file_.hash
        assert result_file['platform'] == 'windows'
        assert result_file['size'] == file_.size
        assert result_file['status'] == 'public'
        assert result_file['url'] == file_.get_url_path(src='')

        assert result['current_version']['edit_url'] == absolutify(
            self.addon.get_dev_url(
                'versions.edit', args=[self.addon.current_version.pk],
                prefix_only=True))
        assert result['current_version']['reviewed'] == version.reviewed
        assert result['current_version']['version'] == version.version
        assert result['current_version']['url'] == absolutify(
            version.get_url_path())

        assert result['authors']
        assert len(result['authors']) == 2
        assert result['authors'][0] == {
            'name': first_author.name,
            'url': absolutify(first_author.get_url_path())}
        assert result['authors'][1] == {
            'name': second_author.name,
            'url': absolutify(second_author.get_url_path())}

        assert result['edit_url'] == absolutify(self.addon.get_dev_url())
        assert result['default_locale'] == self.addon.default_locale
        assert result['description'] == {'en-US': self.addon.description}
        assert result['guid'] == self.addon.guid
        assert result['homepage'] == {'en-US': self.addon.homepage}
        assert result['icon_url'] == absolutify(self.addon.get_icon_url(64))
        assert result['is_listed'] == self.addon.is_listed
        assert result['name'] == {'en-US': self.addon.name}
        assert result['last_updated'] == self.addon.last_updated.isoformat()

        assert result['previews']
        assert len(result['previews']) == 2

        result_preview = result['previews'][0]
        assert result_preview['id'] == first_preview.pk
        assert result_preview['caption'] is None
        assert result_preview['image_url'] == absolutify(
            first_preview.image_url)
        assert result_preview['thumbnail_url'] == absolutify(
            first_preview.thumbnail_url)

        result_preview = result['previews'][1]
        assert result_preview['id'] == second_preview.pk
        assert result_preview['caption'] == {
            'en-US': u'My câption',
            'fr': u'Mön tîtré'
        }
        assert result_preview['image_url'] == absolutify(
            second_preview.image_url)
        assert result_preview['thumbnail_url'] == absolutify(
            second_preview.thumbnail_url)

        assert result['ratings'] == {
            'average': self.addon.average_rating,
            'count': self.addon.total_reviews,
        }
        assert result['public_stats'] == self.addon.public_stats
        assert result['review_url'] == absolutify(
            reverse('editors.review', args=[self.addon.pk]))
        assert result['slug'] == self.addon.slug
        assert result['status'] == 'public'
        assert result['summary'] == {'en-US': self.addon.summary}
        assert result['support_email'] == {'en-US': self.addon.support_email}
        assert result['support_url'] == {'en-US': self.addon.support_url}
        assert 'theme_data' not in result
        assert set(result['tags']) == set(['some_tag', 'some_other_tag'])
        assert result['type'] == 'extension'
        assert result['url'] == absolutify(self.addon.get_url_path())
        return result

    def test_icon_url_without_icon_type_set(self):
        self.addon = addon_factory()
        result = self.serialize()

        assert result['id'] == self.addon.pk
        assert result['icon_url'] == absolutify(self.addon.get_icon_url(64))

    def test_no_current_version(self):
        self.addon = addon_factory(name='lol')
        self.addon.current_version.delete()
        result = self.serialize()

        assert result['id'] == self.addon.pk
        assert result['current_version'] is None

    def test_no_current_version_files(self):
        self.addon = addon_factory(name='lol')
        # Just removing the last file deletes the version, so we have to be
        # creative and replace the version manually with one that has no files.
        self.addon.current_version.delete()
        version = self.addon.versions.create(version='0.42')
        self.addon._current_version = version
        self.addon.save()
        result = self.serialize()

        assert result['id'] == self.addon.pk
        assert result['current_version']
        assert result['current_version']['reviewed'] == version.reviewed
        assert result['current_version']['version'] == version.version
        assert result['current_version']['files'] == []

    def test_deleted(self):
        self.addon = addon_factory(name=u'My Deleted Addôn')
        self.addon.delete()
        result = self.serialize()

        assert result['id'] == self.addon.pk
        assert result['status'] == 'deleted'

    def test_unlisted(self):
        self.addon = addon_factory(name=u'My Unlisted Addôn', is_listed=False)
        result = self.serialize()

        assert result['id'] == self.addon.pk
        assert result['is_listed'] == self.addon.is_listed

    def test_translations(self):
        translated_descriptions = {
            'en-US': u'My Addôn description in english',
            'fr': u'Description de mon Addôn',
        }
        self.addon = addon_factory()
        self.addon.description = translated_descriptions
        self.addon.save()

        result = self.serialize()
        assert result['description'] == translated_descriptions

    def test_persona_with_persona_id(self):
        self.addon = addon_factory(persona_id=42, type=amo.ADDON_PERSONA)
        persona = self.addon.persona
        persona.header = u'myheader.jpg'
        persona.footer = u'myfooter.jpg'
        persona.accentcolor = u'336699'
        persona.textcolor = u'f0f0f0'
        persona.author = u'Me-me-me-Myself'
        persona.display_username = u'my-username'
        persona.save()
        result = self.serialize()
        assert result['theme_data'] == persona.theme_data

    def test_persona(self):
        self.addon = addon_factory(
            name=u'My Personâ',
            description=u'<script>alert(42)</script>My Personä description',
            type=amo.ADDON_PERSONA)
        persona = self.addon.persona
        persona.header = u'myheader.jpg'
        persona.footer = u'myfooter.jpg'
        persona.accentcolor = u'336699'
        persona.textcolor = u'f0f0f0'
        persona.author = u'Me-me-me-Myself'
        persona.display_username = u'my-username'
        persona.save()
        result = self.serialize()
        assert result['theme_data'] == persona.theme_data
        assert '<script>' not in result['theme_data']['description']
        assert '&lt;script&gt;' in result['theme_data']['description']

    def test_handle_persona_without_persona_data_in_db(self):
        self.addon = addon_factory(type=amo.ADDON_PERSONA)
        Persona.objects.get(addon=self.addon).delete()
        # .reload() does not clear self.addon.persona, so do it manually.
        self.addon = Addon.objects.get(pk=self.addon.pk)
        result = self.serialize()

        assert result['id'] == self.addon.pk
        assert result['type'] == 'persona'
        # theme_data should be missing, which sucks, but is better than a 500.
        assert 'theme_data' not in result
        # icon url should just be a default icon instead of the Persona icon.
        assert result['icon_url'] == (
            'http://testserver/static/img/addon-icons/default-64.png')


class TestAddonSerializerOutput(AddonSerializerOutputTestMixin, TestCase):
    def serialize(self):
        serializer = AddonSerializer(context={'request': self.request})
        return serializer.to_representation(self.addon)


class TestESAddonSerializerOutput(AddonSerializerOutputTestMixin, ESTestCase):
    def tearDown(self):
        super(TestESAddonSerializerOutput, self).tearDown()
        self.empty_index('default')
        self.refresh()

    def search(self):
        self.reindex(Addon)

        qs = Search(using=amo.search.get_es(),
                    index=AddonIndexer.get_index_alias(),
                    doc_type=AddonIndexer.get_doctype_name())
        return qs.filter('term', id=self.addon.pk).execute()[0]

    def serialize(self):
        obj = self.search()

        with self.assertNumQueries(0):
            serializer = ESAddonSerializer(context={'request': self.request})
            result = serializer.to_representation(obj)
        return result

    def test_icon_url_without_modified_date(self):
        self.addon = addon_factory(icon_type='image/png')
        self.addon.update(created=datetime(year=1970, day=1, month=1))

        obj = self.search()
        delattr(obj, 'modified')

        with self.assertNumQueries(0):
            serializer = ESAddonSerializer(context={'request': self.request})
            result = serializer.to_representation(obj)

        assert result['id'] == self.addon.pk

        # icon_url should differ, since the serialized result could not use
        # the modification date.
        assert result['icon_url'] != absolutify(self.addon.get_icon_url(64))

        # If we pretend the original add-on modification date is its creation
        # date, then icon_url should be the same, since that's what we do when
        # we don't have a modification date in the serializer.
        self.addon.modified = self.addon.created
        assert result['icon_url'] == absolutify(self.addon.get_icon_url(64))

    def test_handle_persona_without_persona_data_in_index(self):
        """Make sure we handle missing persona data in the index somewhat
        gracefully, because it won't be in it when the commit that uses it
        lands, it will need a reindex first."""
        self.addon = addon_factory(type=amo.ADDON_PERSONA)
        persona = self.addon.persona
        persona.header = u'myheader.jpg'
        persona.footer = u'myfooter.jpg'
        persona.accentcolor = u'336699'
        persona.textcolor = u'f0f0f0'
        persona.author = u'Me-me-me-Myself'
        persona.display_username = u'my-username'
        persona.save()

        obj = self.search()
        delattr(obj, 'persona')

        with self.assertNumQueries(0):
            serializer = ESAddonSerializer(context={'request': self.request})
            result = serializer.to_representation(obj)

        assert 'theme_data' not in result
