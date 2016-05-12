# -*- coding: utf-8 -*-
import uuid

from elasticsearch_dsl import Search
from rest_framework.test import APIRequestFactory

from olympia import amo
from olympia.amo.helpers import absolutify
from olympia.amo.tests import addon_factory, ESTestCase, TestCase
from olympia.amo.urlresolvers import reverse
from olympia.addons.indexers import AddonIndexer
from olympia.addons.models import Addon
from olympia.addons.serializers import AddonSerializer, ESAddonSerializer


class AddonSerializerOutputTestMixin(object):
    """Mixin containing tests to execute on both the regular and the ES Addon
    serializer."""
    def setUp(self):
        self.request = APIRequestFactory().get('/')

    def test_basic(self):
        self.addon = addon_factory(
            description=u'My Addôn description',
            file_kw={
                'hash': 'fakehash',
                'platform': amo.PLATFORM_WIN.id,
                'size': 42,
            },
            guid='{%s}' % uuid.uuid4(),
            homepage=u'https://www.example.org/',
            name=u'My Addôn',
            public_stats=True,
            slug='my-addon',
            summary=u'My Addôn summary',
            support_email=u'support@example.org',
            support_url=u'https://support.example.org/support/my-addon/',
            tags=['some_tag', 'some_other_tag'],
        )

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

        assert result['edit_url'] == absolutify(self.addon.get_dev_url())
        assert result['default_locale'] == self.addon.default_locale
        assert result['description'] == {'en-US': self.addon.description}
        assert result['guid'] == self.addon.guid
        assert result['homepage'] == {'en-US': self.addon.homepage}
        assert result['is_listed'] == self.addon.is_listed
        assert result['name'] == {'en-US': self.addon.name}
        assert result['last_updated'] == self.addon.last_updated.isoformat()
        assert result['public_stats'] == self.addon.public_stats
        assert result['review_url'] == absolutify(
            reverse('editors.review', args=[self.addon.pk]))
        assert result['slug'] == self.addon.slug
        assert result['status'] == 'public'
        assert result['summary'] == {'en-US': self.addon.summary}
        assert result['support_email'] == {'en-US': self.addon.support_email}
        assert result['support_url'] == {'en-US': self.addon.support_url}
        assert set(result['tags']) == set(['some_tag', 'some_other_tag'])
        assert result['type'] == 'extension'
        assert result['url'] == absolutify(self.addon.get_url_path())
        return result

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


class TestAddonSerializerOutput(AddonSerializerOutputTestMixin, TestCase):
    def serialize(self):
        serializer = AddonSerializer(context={'request': self.request})
        return serializer.to_representation(self.addon)


class TestESAddonSerializerOutput(AddonSerializerOutputTestMixin, ESTestCase):
    def tearDown(self):
        super(TestESAddonSerializerOutput, self).tearDown()
        self.empty_index('default')
        self.refresh()

    def serialize(self):
        self.reindex(Addon)

        qs = Search(using=amo.search.get_es(),
                    index=AddonIndexer.get_index_alias(),
                    doc_type=AddonIndexer.get_doctype_name())
        obj = qs.filter('term', id=self.addon.pk).execute()[0]

        with self.assertNumQueries(0):
            serializer = ESAddonSerializer(context={'request': self.request})
            result = serializer.to_representation(obj)
        return result
