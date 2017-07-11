# -*- coding: utf-8 -*-
from django.utils.translation import override

from elasticsearch_dsl import Search
from rest_framework.test import APIRequestFactory

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import (
    addon_factory, ESTestCase, file_factory, TestCase, version_factory,
    user_factory)
from olympia.amo.urlresolvers import get_outgoing_url, reverse
from olympia.addons.indexers import AddonIndexer
from olympia.addons.models import (
    Addon, AddonCategory, AddonUser, Category, Persona, Preview)
from olympia.addons.serializers import (
    AddonSerializer, AddonSerializerWithUnlistedData, ESAddonSerializer,
    ESAddonSerializerWithUnlistedData, SimpleVersionSerializer,
    VersionSerializer)
from olympia.addons.utils import generate_addon_guid
from olympia.constants.categories import CATEGORIES
from olympia.files.models import WebextPermission
from olympia.versions.models import ApplicationsVersions, AppVersion, License


class AddonSerializerOutputTestMixin(object):
    """Mixin containing tests to execute on both the regular and the ES Addon
    serializer."""
    def setUp(self):
        super(AddonSerializerOutputTestMixin, self).setUp()
        self.request = APIRequestFactory().get('/')

    def check_author(self, author, result):
        assert result == {
            'id': author.pk,
            'name': author.name,
            'url': absolutify(author.get_url_path()),
            'picture_url': absolutify(author.picture_url)}

    def _test_version(self, version, data):
        assert data['id'] == version.pk

        assert data['compatibility']
        assert len(data['compatibility']) == len(version.compatible_apps)
        for app, compat in version.compatible_apps.items():
            assert data['compatibility'][app.short] == {
                'min': compat.min.version,
                'max': compat.max.version
            }
        assert data['files']
        assert len(data['files']) == 1

        result_file = data['files'][0]
        file_ = version.files.latest('pk')
        assert result_file['id'] == file_.pk
        assert result_file['created'] == (
            file_.created.replace(microsecond=0).isoformat() + 'Z')
        assert result_file['hash'] == file_.hash
        assert result_file['is_restart_required'] == file_.is_restart_required
        assert result_file['is_webextension'] == file_.is_webextension
        assert result_file['platform'] == (
            amo.PLATFORM_CHOICES_API[file_.platform])
        assert result_file['size'] == file_.size
        assert result_file['status'] == amo.STATUS_CHOICES_API[file_.status]
        assert result_file['url'] == file_.get_url_path(src='')
        assert result_file['permissions'] == file_.webext_permissions_list

        assert data['edit_url'] == absolutify(
            self.addon.get_dev_url(
                'versions.edit', args=[version.pk], prefix_only=True))
        assert data['reviewed'] == version.reviewed
        assert data['version'] == version.version
        assert data['url'] == absolutify(version.get_url_path())

    def test_basic(self):
        cat1 = Category.from_static_category(
            CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION]['bookmarks'])
        cat1.save()
        self.addon = addon_factory(
            average_daily_users=4242,
            average_rating=4.21,
            bayesian_rating=4.22,
            category=cat1,
            description=u'My Addôn description',
            file_kw={
                'hash': 'fakehash',
                'is_restart_required': False,
                'is_webextension': True,
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
            weekly_downloads=2147483647,
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

        av_min = AppVersion.objects.get_or_create(
            application=amo.THUNDERBIRD.id, version='2.0.99')[0]
        av_max = AppVersion.objects.get_or_create(
            application=amo.THUNDERBIRD.id, version='3.0.99')[0]
        ApplicationsVersions.objects.get_or_create(
            application=amo.THUNDERBIRD.id, version=self.addon.current_version,
            min=av_min, max=av_max)
        # Reset current_version.compatible_apps now that we've added an app.
        del self.addon.current_version.compatible_apps

        cat2 = Category.from_static_category(
            CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION]['alerts-updates'])
        cat2.save()
        AddonCategory.objects.create(addon=self.addon, category=cat2)
        cat3 = Category.from_static_category(
            CATEGORIES[amo.THUNDERBIRD.id][amo.ADDON_EXTENSION]['calendar'])
        cat3.save()
        AddonCategory.objects.create(addon=self.addon, category=cat3)

        result = self.serialize()

        assert result['id'] == self.addon.pk

        assert result['average_daily_users'] == self.addon.average_daily_users
        assert result['categories'] == {
            'firefox': ['alerts-updates', 'bookmarks'],
            'thunderbird': ['calendar']}

        assert result['current_beta_version'] is None

        # In this serializer latest_unlisted_version is omitted.
        assert 'latest_unlisted_version' not in result

        assert result['current_version']
        self._test_version(
            self.addon.current_version, result['current_version'])
        assert result['current_version']['url'] == absolutify(
            reverse('addons.versions',
                    args=[self.addon.slug, self.addon.current_version.version])
        )

        assert result['authors']
        assert len(result['authors']) == 2
        self.check_author(first_author, result['authors'][0])
        self.check_author(second_author, result['authors'][1])

        assert result['edit_url'] == absolutify(self.addon.get_dev_url())
        assert result['default_locale'] == self.addon.default_locale
        assert result['description'] == {'en-US': self.addon.description}
        assert result['guid'] == self.addon.guid
        assert result['has_eula'] is False
        assert result['has_privacy_policy'] is False
        assert result['homepage'] == {
            'en-US': get_outgoing_url(unicode(self.addon.homepage))
        }
        assert result['icon_url'] == absolutify(self.addon.get_icon_url(64))
        assert result['is_disabled'] == self.addon.is_disabled
        assert result['is_experimental'] == self.addon.is_experimental is False
        assert result['is_source_public'] == self.addon.view_source
        assert result['last_updated'] == (
            self.addon.last_updated.replace(microsecond=0).isoformat() + 'Z')
        assert result['name'] == {'en-US': self.addon.name}
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
            'bayesian_average': self.addon.bayesian_rating,
            'count': self.addon.total_reviews,
        }
        assert result['public_stats'] == self.addon.public_stats
        assert result['review_url'] == absolutify(
            reverse('editors.review', args=[self.addon.pk]))
        assert result['slug'] == self.addon.slug
        assert result['status'] == 'public'
        assert result['summary'] == {'en-US': self.addon.summary}
        assert result['support_email'] == {'en-US': self.addon.support_email}
        assert result['support_url'] == {
            'en-US': get_outgoing_url(unicode(self.addon.support_url))
        }
        assert 'theme_data' not in result
        assert set(result['tags']) == set(['some_tag', 'some_other_tag'])
        assert result['type'] == 'extension'
        assert result['url'] == absolutify(self.addon.get_url_path())
        assert result['weekly_downloads'] == self.addon.weekly_downloads

        return result

    def test_latest_unlisted_version(self):
        self.addon = addon_factory()
        version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED,
            version='1.1')
        assert self.addon.latest_unlisted_version

        result = self.serialize()
        # In this serializer latest_unlisted_version is omitted even if there
        # is one, because it's limited to users with specific rights.
        assert 'latest_unlisted_version' not in result

    def test_latest_unlisted_version_with_rights(self):
        self.serializer_class = self.serializer_class_with_unlisted_data

        self.addon = addon_factory()
        version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED,
            version='1.1')
        assert self.addon.latest_unlisted_version

        result = self.serialize()
        # In this serializer latest_unlisted_version is present.
        assert result['latest_unlisted_version']
        self._test_version(
            self.addon.latest_unlisted_version,
            result['latest_unlisted_version'])
        assert result['latest_unlisted_version']['url'] == absolutify('')

    def test_current_beta_version(self):
        self.addon = addon_factory()

        self.beta_version = version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_BETA},
            version='1.1beta')

        result = self.serialize()
        assert result['current_beta_version']
        self._test_version(self.beta_version, result['current_beta_version'], )
        assert result['current_beta_version']['url'] == absolutify(
            reverse('addons.versions',
                    args=[self.addon.slug, self.beta_version.version])
        )

        # Just in case, test that current version is still present & different.
        assert result['current_version']
        assert result['current_version'] != result['current_beta_version']
        self._test_version(
            self.addon.current_version, result['current_version'])

    def test_is_disabled(self):
        self.addon = addon_factory(disabled_by_user=True)
        result = self.serialize()

        assert result['is_disabled'] is True

    def test_is_source_public(self):
        self.addon = addon_factory(view_source=True)
        result = self.serialize()

        assert result['is_source_public'] is True

    def test_is_experimental(self):
        self.addon = addon_factory(is_experimental=True)
        result = self.serialize()

        assert result['is_experimental'] is True

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

    def test_has_policies(self):
        self.addon = addon_factory()
        self.addon.eula = {
            'en-US': u'My Addôn EULA in english',
            'fr': u'Houlalà',
        }
        self.addon.privacy_policy = 'lol'
        self.addon.save()

        result = self.serialize()
        assert result['has_eula'] is True
        assert result['has_privacy_policy'] is True

    def test_translations(self):
        translated_descriptions = {
            'en-US': u'My Addôn description in english',
            'fr': u'Description de mon Addôn',
        }
        translated_homepages = {
            'en-US': u'http://www.google.com/',
            'fr': u'http://www.googlé.fr/',
        }
        self.addon = addon_factory()
        self.addon.description = translated_descriptions
        self.addon.homepage = translated_homepages
        self.addon.save()

        result = self.serialize()
        assert result['description'] == translated_descriptions
        assert result['homepage'] != translated_homepages
        assert result['homepage'] == {
            'en-US': get_outgoing_url(translated_homepages['en-US']),
            'fr': get_outgoing_url(translated_homepages['fr'])
        }

        # Try a single translation. The locale activation is normally done by
        # LocaleAndAppURLMiddleware, but since we're directly calling the
        # serializer we need to do it ourselves.
        self.request = APIRequestFactory().get('/', {'lang': 'fr'})
        with override('fr'):
            result = self.serialize()
        assert result['description'] == translated_descriptions['fr']
        assert result['homepage'] == get_outgoing_url(
            translated_homepages['fr'])

    def test_persona_with_persona_id(self):
        self.addon = addon_factory(type=amo.ADDON_PERSONA)
        persona = self.addon.persona
        persona.persona_id = 42
        persona.header = u'myheader.jpg'
        persona.footer = u'myfooter.jpg'
        persona.accentcolor = u'336699'
        persona.textcolor = u'f0f0f0'
        persona.author = u'Me-me-me-Myself'
        persona.display_username = u'my-username'
        persona.save()
        assert not persona.is_new()

        result = self.serialize()
        assert result['theme_data'] == persona.theme_data

    def test_persona(self):
        self.addon = addon_factory(
            name=u'My Personâ',
            description=u'<script>alert(42)</script>My Personä description',
            type=amo.ADDON_PERSONA)
        persona = self.addon.persona
        persona.persona_id = 0  # For "new" style Personas this is always 0.
        persona.header = u'myheader.png'
        persona.footer = u'myfooter.png'
        persona.accentcolor = u'336699'
        persona.textcolor = u'f0f0f0'
        persona.author = u'Me-me-me-Myself'
        persona.display_username = u'my-username'
        persona.save()
        assert persona.is_new()

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

    def test_webextension(self):
        self.addon = addon_factory(file_kw={'is_webextension': True})
        # Give one of the versions some webext permissions to test that.
        WebextPermission.objects.create(
            file=self.addon.current_version.all_files[0],
            permissions=['bookmarks', 'random permission']
        )

        result = self.serialize()

        self._test_version(
            self.addon.current_version, result['current_version'])
        # Double check the permissions got correctly set.
        assert result['current_version']['files'][0]['permissions'] == ([
            'bookmarks', 'random permission'])

    def test_is_restart_required(self):
        self.addon = addon_factory(file_kw={'is_restart_required': True})
        result = self.serialize()

        self._test_version(
            self.addon.current_version, result['current_version'])


class TestAddonSerializerOutput(AddonSerializerOutputTestMixin, TestCase):
    serializer_class = AddonSerializer
    serializer_class_with_unlisted_data = AddonSerializerWithUnlistedData

    def serialize(self):
        self.serializer = self.serializer_class(
            context={'request': self.request})
        # Manually reload the add-on first to clear any cached properties.
        self.addon = Addon.unfiltered.get(pk=self.addon.pk)
        return self.serializer.to_representation(self.addon)


class TestESAddonSerializerOutput(AddonSerializerOutputTestMixin, ESTestCase):
    serializer_class = ESAddonSerializer
    serializer_class_with_unlisted_data = ESAddonSerializerWithUnlistedData

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
        self.serializer = self.serializer_class(
            context={'request': self.request})

        obj = self.search()

        with self.assertNumQueries(0):
            result = self.serializer.to_representation(obj)
        return result

    def check_author(self, author, result):
        """Override because the ES serializer doesn't include picture_url."""
        assert result == {
            'id': author.pk,
            'name': author.name,
            'url': absolutify(author.get_url_path())}


class TestVersionSerializerOutput(TestCase):
    def setUp(self):
        super(TestVersionSerializerOutput, self).setUp()
        self.request = APIRequestFactory().get('/')

    def serialize(self):
        serializer = VersionSerializer(context={'request': self.request})
        return serializer.to_representation(self.version)

    def test_basic(self):
        now = self.days_ago(0)
        license = License.objects.create(
            name={
                'en-US': u'My License',
                'fr': u'Mä Licence',
            },
            text={
                'en-US': u'Lorem ipsum dolor sit amet, has nemore patrioqué',
            },
            url='http://license.example.com/'

        )
        addon = addon_factory(
            file_kw={
                'hash': 'fakehash',
                'is_webextension': True,
                'platform': amo.PLATFORM_WIN.id,
                'size': 42,
            },
            version_kw={
                'license': license,
                'min_app_version': '50.0',
                'max_app_version': '*',
                'releasenotes': {
                    'en-US': u'Release notes in english',
                    'fr': u'Notes de version en français',
                },
                'reviewed': now,
            }
        )

        self.version = addon.current_version
        first_file = self.version.files.latest('pk')
        file_factory(
            version=self.version, platform=amo.PLATFORM_MAC.id)
        second_file = self.version.files.latest('pk')
        # Force reload of all_files cached property.
        del self.version.all_files

        result = self.serialize()
        assert result['id'] == self.version.pk

        assert result['compatibility'] == {
            'firefox': {'max': u'*', 'min': u'50.0'}
        }

        assert result['files']
        assert len(result['files']) == 2

        assert result['files'][0]['id'] == first_file.pk
        assert result['files'][0]['created'] == (
            first_file.created.replace(microsecond=0).isoformat() + 'Z')
        assert result['files'][0]['hash'] == first_file.hash
        assert result['files'][0]['is_webextension'] == (
            first_file.is_webextension)
        assert result['files'][0]['platform'] == 'windows'
        assert result['files'][0]['size'] == first_file.size
        assert result['files'][0]['status'] == 'public'
        assert result['files'][0]['url'] == first_file.get_url_path(src='')

        assert result['files'][1]['id'] == second_file.pk
        assert result['files'][1]['created'] == (
            second_file.created.replace(microsecond=0).isoformat() + 'Z')
        assert result['files'][1]['hash'] == second_file.hash
        assert result['files'][1]['is_webextension'] == (
            second_file.is_webextension)
        assert result['files'][1]['platform'] == 'mac'
        assert result['files'][1]['size'] == second_file.size
        assert result['files'][1]['status'] == 'public'
        assert result['files'][1]['url'] == second_file.get_url_path(src='')

        assert result['channel'] == 'listed'
        assert result['edit_url'] == absolutify(addon.get_dev_url(
            'versions.edit', args=[self.version.pk], prefix_only=True))
        assert result['release_notes'] == {
            'en-US': u'Release notes in english',
            'fr': u'Notes de version en français',
        }
        assert result['license']
        assert dict(result['license']) == {
            'id': license.pk,
            'name': {'en-US': u'My License', 'fr': u'Mä Licence'},
            'text': {
                'en-US': u'Lorem ipsum dolor sit amet, has nemore patrioqué',
            },
            'url': 'http://license.example.com/',
        }
        assert result['reviewed'] == (
            now.replace(microsecond=0).isoformat() + 'Z')
        assert result['url'] == absolutify(self.version.get_url_path())

    def test_unlisted(self):
        addon = addon_factory()
        self.version = version_factory(
            addon=addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        result = self.serialize()
        assert result['channel'] == 'unlisted'

    def test_no_license(self):
        addon = addon_factory()
        self.version = addon.current_version
        self.version.update(license=None)
        result = self.serialize()
        assert result['id'] == self.version.pk
        assert result['license'] is None

    def test_file_webext_permissions(self):
        self.version = addon_factory().current_version
        result = self.serialize()
        # No permissions.
        assert result['files'][0]['permissions'] == []

        self.version = addon_factory(
            file_kw={'is_webextension': True}).current_version
        permissions = ['dangerdanger', 'high', 'voltage']
        WebextPermission.objects.create(
            permissions=permissions, file=self.version.all_files[0])
        result = self.serialize()
        assert result['files'][0]['permissions'] == permissions


class TestSimpleVersionSerializerOutput(TestCase):
    def setUp(self):
        self.request = APIRequestFactory().get('/')

    def serialize(self):
        serializer = SimpleVersionSerializer(context={'request': self.request})
        return serializer.to_representation(self.version)

    def test_license_included_without_text(self):
        now = self.days_ago(0)
        license = License.objects.create(
            name={
                'en-US': u'My License',
                'fr': u'Mä Licence',
            },
            text={
                'en-US': u'Lorem ipsum dolor sit amet, has nemore patrioqué',
            },
            url='http://license.example.com/'

        )
        addon = addon_factory(
            version_kw={
                'license': license,
                'reviewed': now,
            }
        )

        self.version = addon.current_version

        result = self.serialize()
        assert result['id'] == self.version.pk
        assert result['license'] is not None
        assert result['license']['id'] == license.pk
        assert result['license']['name']['en-US'] == 'My License'
        assert result['license']['name']['fr'] == u'Mä Licence'
        assert result['license']['url'] == 'http://license.example.com/'
        assert 'text' not in result['license']
