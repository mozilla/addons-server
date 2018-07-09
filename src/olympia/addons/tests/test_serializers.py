# -*- coding: utf-8 -*-
from django.utils.translation import override

from rest_framework.test import APIRequestFactory

from olympia import amo
from olympia.accounts.tests.test_serializers import TestBaseUserSerializer
from olympia.addons.models import (
    Addon, AddonCategory, AddonUser, Category, CompatOverride,
    CompatOverrideRange, Persona, Preview, ReplacementAddon)
from olympia.addons.serializers import (
    AddonDeveloperSerializer, AddonSerializer, AddonSerializerWithUnlistedData,
    CompatOverrideSerializer, ESAddonAutoCompleteSerializer, ESAddonSerializer,
    ESAddonSerializerWithUnlistedData, LanguageToolsSerializer,
    LicenseSerializer, ReplacementAddonSerializer, SimpleVersionSerializer,
    VersionSerializer)
from olympia.addons.utils import generate_addon_guid
from olympia.addons.views import AddonAutoCompleteSearchView, AddonSearchView
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import (
    ESTestCase, TestCase, addon_factory, collection_factory, file_factory,
    user_factory, version_factory)
from olympia.amo.urlresolvers import get_outgoing_url, reverse
from olympia.bandwagon.models import FeaturedCollection
from olympia.constants.categories import CATEGORIES
from olympia.constants.licenses import LICENSES_BY_BUILTIN
from olympia.files.models import WebextPermission
from olympia.versions.models import (
    ApplicationsVersions, AppVersion, License, VersionPreview)


class AddonSerializerOutputTestMixin(object):
    """Mixin containing tests to execute on both the regular and the ES Addon
    serializer."""
    def setUp(self):
        super(AddonSerializerOutputTestMixin, self).setUp()
        self.request = APIRequestFactory().get('/')

    def _test_author(self, author, data):
        assert data == {
            'id': author.pk,
            'name': author.name,
            'picture_url': None,
            'url': absolutify(author.get_url_path()),
            'username': author.username,
        }

    def _test_version_license_and_release_notes(self, version, data):
        assert data['release_notes'] == {
            'en-US': u'Release notes in english',
            'fr': u'Notes de version en français',
        }
        assert data['license']
        assert dict(data['license']) == {
            'id': version.license.pk,
            'name': {'en-US': u'My License', 'fr': u'Mä Licence'},
            # License text is not present in version serializer used from
            # AddonSerializer.
            'url': 'http://license.example.com/',
        }

    def _test_version(self, version, data):
        assert data['id'] == version.pk

        assert data['compatibility']
        assert len(data['compatibility']) == len(version.compatible_apps)
        for app, compat in version.compatible_apps.items():
            assert data['compatibility'][app.short] == {
                'min': compat.min.version,
                'max': compat.max.version
            }
        assert data['is_strict_compatibility_enabled'] is False
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
        assert (
            result_file['is_mozilla_signed_extension'] ==
            file_.is_mozilla_signed_extension)
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
        self.addon = addon_factory(
            average_daily_users=4242,
            average_rating=4.21,
            bayesian_rating=4.22,
            category=cat1,
            contributions=u'https://paypal.me/foobar/',
            description=u'My Addôn description',
            developer_comments=u'Dévelopers Addôn comments',
            file_kw={
                'hash': 'fakehash',
                'is_restart_required': False,
                'is_webextension': True,
                'platform': amo.PLATFORM_WIN.id,
                'size': 42,
            },
            guid=generate_addon_guid(),
            homepage=u'https://www.example.org/',
            icon_hash='fakehash',
            icon_type='image/png',
            name=u'My Addôn',
            public_stats=True,
            slug='my-addon',
            summary=u'My Addôn summary',
            support_email=u'support@example.org',
            support_url=u'https://support.example.org/support/my-addon/',
            tags=['some_tag', 'some_other_tag'],
            total_ratings=666,
            text_ratings_count=555,
            version_kw={
                'license': license,
                'releasenotes': {
                    'en-US': u'Release notes in english',
                    'fr': u'Notes de version en français',
                },
            },
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
            caption={'en-US': u'My câption', 'fr': u'Mön tîtré'},
            sizes={'thumbnail': [199, 99], 'image': [567, 780]})
        first_preview = Preview.objects.create(addon=self.addon, position=1)

        av_min = AppVersion.objects.get_or_create(
            application=amo.THUNDERBIRD.id, version='2.0.99')[0]
        av_max = AppVersion.objects.get_or_create(
            application=amo.THUNDERBIRD.id, version='3.0.99')[0]
        ApplicationsVersions.objects.get_or_create(
            application=amo.THUNDERBIRD.id, version=self.addon.current_version,
            min=av_min, max=av_max)
        # Reset current_version.compatible_apps now that we've added an app.
        del self.addon.current_version._compatible_apps

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

        # In this serializer latest_unlisted_version is omitted.
        assert 'latest_unlisted_version' not in result

        assert result['current_version']
        self._test_version(
            self.addon.current_version, result['current_version'])
        assert result['current_version']['url'] == absolutify(
            reverse('addons.versions',
                    args=[self.addon.slug, self.addon.current_version.version])
        )
        self._test_version_license_and_release_notes(
            self.addon.current_version, result['current_version'])

        assert result['authors']
        assert len(result['authors']) == 2
        self._test_author(first_author, result['authors'][0])
        self._test_author(second_author, result['authors'][1])

        assert result['contributions_url'] == self.addon.contributions
        assert result['edit_url'] == absolutify(self.addon.get_dev_url())
        assert result['default_locale'] == self.addon.default_locale
        assert result['description'] == {'en-US': self.addon.description}
        assert result['developer_comments'] == {
            'en-US': self.addon.developer_comments}
        assert result['guid'] == self.addon.guid
        assert result['has_eula'] is False
        assert result['has_privacy_policy'] is False
        assert result['homepage'] == {
            'en-US': unicode(self.addon.homepage),
        }
        assert result['icon_url'] == absolutify(self.addon.get_icon_url(64))
        assert result['icons'] == {
            '32': absolutify(self.addon.get_icon_url(32)),
            '64': absolutify(self.addon.get_icon_url(64))
        }
        assert result['is_disabled'] == self.addon.is_disabled
        assert result['is_experimental'] == self.addon.is_experimental is False
        assert result['is_featured'] == self.addon.is_featured() is False
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
        assert result_preview['image_size'] == first_preview.image_size
        assert result_preview['thumbnail_size'] == first_preview.thumbnail_size

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
        assert (result_preview['image_size'] == second_preview.image_size ==
                [567, 780])
        assert (result_preview['thumbnail_size'] ==
                second_preview.thumbnail_size == [199, 99])

        assert result['ratings'] == {
            'average': self.addon.average_rating,
            'bayesian_average': self.addon.bayesian_rating,
            'count': self.addon.total_ratings,
            'text_count': self.addon.text_ratings_count,
        }
        assert (
            result['ratings_url'] == absolutify(self.addon.ratings_url) ==
            absolutify(reverse('addons.ratings.list', args=[self.addon.slug])))
        assert result['public_stats'] == self.addon.public_stats
        assert result['requires_payment'] == self.addon.requires_payment
        assert result['review_url'] == absolutify(
            reverse('reviewers.review', args=[self.addon.pk]))
        assert result['slug'] == self.addon.slug
        assert result['status'] == 'public'
        assert result['summary'] == {'en-US': self.addon.summary}
        assert result['support_email'] == {'en-US': self.addon.support_email}
        assert result['support_url'] == {
            'en-US': unicode(self.addon.support_url),
        }
        assert 'theme_data' not in result
        assert set(result['tags']) == set(['some_tag', 'some_other_tag'])
        assert result['type'] == 'extension'
        assert result['url'] == absolutify(self.addon.get_url_path())
        assert result['weekly_downloads'] == self.addon.weekly_downloads

        return result

    def test_wrap_outgoing_links(self):
        self.addon = addon_factory(
            contributions=u'https://paypal.me/fôobar',
            homepage='http://support.example.com/',
            support_url=u'https://support.example.org/support/my-âddon/')
        self.request = APIRequestFactory().get('/', {'wrap_outgoing_links': 1})
        result = self.serialize()
        assert result['contributions_url'] == (
            get_outgoing_url(unicode(self.addon.contributions)))
        assert result['homepage'] == {
            'en-US': get_outgoing_url(unicode(self.addon.homepage)),
        }
        assert result['support_url'] == {
            'en-US': get_outgoing_url(unicode(self.addon.support_url)),
        }

        # Try a single translation.
        self.request = APIRequestFactory().get('/', {
            'lang': 'en-US', 'wrap_outgoing_links': 1})
        result = self.serialize()
        assert result['contributions_url'] == (
            get_outgoing_url(unicode(self.addon.contributions)))
        assert result['homepage'] == (
            get_outgoing_url(unicode(self.addon.homepage))
        )
        assert result['support_url'] == (
            get_outgoing_url(unicode(self.addon.support_url))
        )

        # Try with empty strings/None. Annoyingly, contribution model field
        # does not let us set it to None, so use a translated field for that
        # part of the test.
        self.addon.update(contributions='', homepage=None)
        result = self.serialize()
        assert result['contributions_url'] == ''
        assert result['homepage'] is None

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

    def test_requires_payment(self):
        self.addon = addon_factory(requires_payment=True)
        result = self.serialize()

        assert result['requires_payment'] is True

    def test_icon_url_without_icon_type_set(self):
        self.addon = addon_factory()
        result = self.serialize()

        assert result['id'] == self.addon.pk
        assert result['icon_url'] == absolutify(self.addon.get_icon_url(64))
        assert result['icons'] == {
            '32': absolutify(self.addon.get_icon_url(32)),
            '64': absolutify(self.addon.get_icon_url(64))
        }

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
        result_version = result['current_version']
        assert result_version['reviewed'] == version.reviewed
        assert result_version['version'] == version.version
        assert result_version['files'] == []
        assert result_version['is_strict_compatibility_enabled'] is False
        assert result_version['compatibility'] == {}

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

    def test_is_featured(self):
        self.addon = addon_factory()
        collection = collection_factory()
        FeaturedCollection.objects.create(collection=collection,
                                          application=collection.application)
        collection.add_addon(self.addon)
        assert self.addon.is_featured()

        result = self.serialize()
        assert result['is_featured'] is True

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
        assert result['homepage'] == translated_homepages

        # Try a single translation. The locale activation is normally done by
        # LocaleAndAppURLMiddleware, but since we're directly calling the
        # serializer we need to do it ourselves.
        self.request = APIRequestFactory().get('/', {'lang': 'fr'})
        with override('fr'):
            result = self.serialize()
        assert result['description'] == translated_descriptions['fr']
        assert result['homepage'] == translated_homepages['fr']

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
        persona.popularity = 123456
        persona.save()
        assert persona.is_new()

        result = self.serialize()
        assert result['theme_data'] == persona.theme_data
        assert '<script>' not in result['theme_data']['description']
        assert '&lt;script&gt;' in result['theme_data']['description']

        assert result['average_daily_users'] == persona.popularity

        assert 'weekly_downloads' not in result

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
        assert result['icons'] == {
            '32': 'http://testserver/static/img/addon-icons/default-32.png',
            '64': 'http://testserver/static/img/addon-icons/default-64.png'
        }

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

    def test_special_compatibility_cases(self):
        # Test an add-on with strict compatibility enabled.
        self.addon = addon_factory(file_kw={'strict_compatibility': True})
        result_version = self.serialize()['current_version']
        assert result_version['compatibility'] == {
            'firefox': {'max': u'5.0.99', 'min': u'4.0.99'}
        }
        assert result_version['is_strict_compatibility_enabled'] is True

        # Test an add-on with no compatibility info.
        self.addon = addon_factory()
        ApplicationsVersions.objects.filter(
            version=self.addon.current_version).delete()
        result_version = self.serialize()['current_version']
        assert result_version['compatibility'] == {}
        assert result_version['is_strict_compatibility_enabled'] is False

        # Test an add-on with some compatibility info but that should be
        # ignored because its type is in NO_COMPAT.
        self.addon = addon_factory(type=amo.ADDON_SEARCH)
        av_min = AppVersion.objects.get_or_create(
            application=amo.THUNDERBIRD.id, version='2.0.99')[0]
        av_max = AppVersion.objects.get_or_create(
            application=amo.THUNDERBIRD.id, version='3.0.99')[0]
        ApplicationsVersions.objects.get_or_create(
            application=amo.THUNDERBIRD.id, version=self.addon.current_version,
            min=av_min, max=av_max)
        result_version = self.serialize()['current_version']
        assert result_version['compatibility'] == {
            'android': {'max': '9999', 'min': '11.0'},
            'firefox': {'max': '9999', 'min': '4.0'},
            'seamonkey': {'max': '9999', 'min': '2.1'},
            # No thunderbird: it does not support that type, and when we return
            # fake compatibility data for NO_COMPAT add-ons we do obey that.
        }
        assert result_version['is_strict_compatibility_enabled'] is False

    def test_static_theme_preview(self):
        self.addon = addon_factory(type=amo.ADDON_STATICTHEME)
        # Attach some Preview instances do the add-on, they should be ignored
        # since it's a static theme.
        Preview.objects.create(
            addon=self.addon, position=1,
            caption={'en-US': u'My câption', 'fr': u'Mön tîtré'},
            sizes={'thumbnail': [123, 45], 'image': [678, 910]})
        result = self.serialize()
        assert result['previews'] == []

        # Add a second version, attach VersionPreview to both, make sure we
        # take the right one.
        first_version = self.addon.current_version
        VersionPreview.objects.create(
            version=first_version,
            sizes={'thumbnail': [12, 34], 'image': [56, 78]})
        second_version = version_factory(addon=self.addon)
        current_preview = VersionPreview.objects.create(
            version=second_version,
            sizes={'thumbnail': [56, 78], 'image': [91, 234]})
        assert self.addon.reload().current_version == second_version
        result = self.serialize()
        assert len(result['previews']) == 1
        assert result['previews'][0]['id'] == current_preview.pk
        assert result['previews'][0]['caption'] is None
        assert result['previews'][0]['image_url'] == absolutify(
            current_preview.image_url)
        assert result['previews'][0]['thumbnail_url'] == absolutify(
            current_preview.thumbnail_url)
        assert result['previews'][0]['image_size'] == (
            current_preview.image_size)
        assert result['previews'][0]['thumbnail_size'] == (
            current_preview.thumbnail_size)

        # Make sure we don't fail if somehow there is no current version.
        self.addon.update(_current_version=None)
        result = self.serialize()
        assert result['current_version'] is None
        assert result['previews'] == []


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

        view = AddonSearchView()
        view.request = self.request
        qs = view.get_queryset()

        return qs.filter('term', id=self.addon.pk).execute()[0]

    def serialize(self):
        self.serializer = self.serializer_class(
            context={'request': self.request})

        obj = self.search()

        with self.assertNumQueries(0):
            result = self.serializer.to_representation(obj)
        return result

    def _test_author(self, author, data):
        """Override because the ES serializer doesn't include picture_url."""
        assert data == {
            'id': author.pk,
            'name': author.name,
            'url': absolutify(author.get_url_path()),
            'username': author.username,
        }

    def _test_version_license_and_release_notes(self, version, data):
        """Override because the ES serializer doesn't include those fields."""
        assert 'license' not in data
        assert 'release_notes' not in data


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
                'is_mozilla_signed_extension': True,
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
        assert result['files'][0]['is_mozilla_signed_extension'] == (
            first_file.is_mozilla_signed_extension)
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
        assert result['files'][1]['is_mozilla_signed_extension'] == (
            second_file.is_mozilla_signed_extension)
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

    def test_license_no_url(self):
        addon = addon_factory()
        self.version = addon.current_version
        license = self.version.license
        license.update(url=None, builtin=license.OTHER)
        result = self.serialize()
        assert result['id'] == self.version.pk
        assert result['license']
        assert result['license']['id'] == license.pk
        assert result['license']['url'] == absolutify(
            self.version.license_url())

        license.update(builtin=1)
        result = self.serialize()
        # Builtin licenses with no url shouldn't get the version license url.
        assert result['license']['url'] is None

    def test_license_serializer_no_url_no_parent(self):
        # This should not happen (LicenseSerializer should always be called
        # from a parent VersionSerializer) but we don't want the API to 500
        # if that does happens.
        addon = addon_factory()
        self.version = addon.current_version
        license = self.version.license
        license.update(url=None)
        result = LicenseSerializer(
            context={'request': self.request}).to_representation(license)
        assert result['id'] == license.pk
        # LicenseSerializer is unable to find the Version, so it falls back to
        # None.
        assert result['url'] is None

    def test_builtin_license(self):
        addon = addon_factory()
        self.version = addon.current_version
        license = self.version.license
        license.update(builtin=18)
        assert license._constant == LICENSES_BY_BUILTIN[18]

        result = LicenseSerializer(
            context={'request': self.request}).to_representation(license)
        assert result['id'] == license.pk
        # A request with no ?lang gets you the site default l10n in a dict to
        # match how non-constant values are returned.
        assert result['name'] == {
            'en-US': unicode(LICENSES_BY_BUILTIN[18].name)}

        accept_request = APIRequestFactory().get('/')
        accept_request.LANG = 'de'
        result = LicenseSerializer(
            context={'request': accept_request}).to_representation(license)
        # An Accept-Language should result in a different default though.
        assert result['name'] == {
            'de': unicode(LICENSES_BY_BUILTIN[18].name)}

        # But a requested lang returns a flat string
        lang_request = APIRequestFactory().get('/?lang=fr')
        result = LicenseSerializer(
            context={'request': lang_request}).to_representation(license)
        assert result['name'] == unicode(LICENSES_BY_BUILTIN[18].name)

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


class TestLanguageToolsSerializerOutput(TestCase):
    def setUp(self):
        self.request = APIRequestFactory().get('/')

    def serialize(self):
        serializer = LanguageToolsSerializer(context={'request': self.request})
        return serializer.to_representation(self.addon)

    def test_basic(self):
        self.addon = addon_factory(
            type=amo.ADDON_LPAPP, target_locale='fr',
            locale_disambiguation=u'lolé')
        result = self.serialize()
        assert result['id'] == self.addon.pk
        assert result['default_locale'] == self.addon.default_locale
        assert result['guid'] == self.addon.guid
        assert result['locale_disambiguation'] == (
            self.addon.locale_disambiguation)
        assert result['name'] == {'en-US': self.addon.name}
        assert result['slug'] == self.addon.slug
        assert result['target_locale'] == self.addon.target_locale
        assert result['type'] == 'language'
        assert result['url'] == absolutify(self.addon.get_url_path())
        assert 'current_compatible_version' not in result

    def test_basic_dict(self):
        self.addon = addon_factory(type=amo.ADDON_DICT)
        result = self.serialize()
        assert result['type'] == 'dictionary'
        assert 'current_compatible_version' not in result

    def test_current_compatible_version(self):
        # Set a filename to make sure the file actually exists.
        # file_factory (used via addon_factory) copies files that exists
        # as fixtures in src/olympia/files/fixtures/files to their rightful
        # place. We need that to test the localepicker properly.
        file_kw = {'filename': 'langpack-localepicker.xpi'}
        self.addon = addon_factory(type=amo.ADDON_LPAPP, file_kw=file_kw)

        # compatible_versions is set by the view through prefetch, it
        # looks like a list.
        self.addon.compatible_versions = [self.addon.current_version]
        self.addon.compatible_versions[0].update(created=self.days_ago(1))
        # Create a new current version, just to prove that
        # current_compatible_version does not use that.
        version_factory(addon=self.addon, file_kw=file_kw)
        self.addon.reload
        assert (
            self.addon.compatible_versions[0] !=
            self.addon.current_version)
        self.request = APIRequestFactory().get('/?app=firefox&appversion=57.0')
        result = self.serialize()
        assert 'current_compatible_version' in result
        assert result['current_compatible_version'] is not None
        assert set(result['current_compatible_version'].keys()) == set(
            ['id', 'files', 'reviewed', 'version'])

        self.addon.compatible_versions = None
        result = self.serialize()
        assert 'current_compatible_version' in result
        assert result['current_compatible_version'] is None

        self.addon.compatible_versions = []
        result = self.serialize()
        assert 'current_compatible_version' in result
        assert result['current_compatible_version'] is None


class TestESAddonAutoCompleteSerializer(ESTestCase):
    def setUp(self):
        super(TestESAddonAutoCompleteSerializer, self).setUp()
        self.request = APIRequestFactory().get('/')

    def tearDown(self):
        super(TestESAddonAutoCompleteSerializer, self).tearDown()
        self.empty_index('default')
        self.refresh()

    def search(self):
        self.reindex(Addon)

        view = AddonAutoCompleteSearchView()
        view.request = self.request
        qs = view.get_queryset()
        return qs.filter('term', id=self.addon.pk).execute()[0]

    def serialize(self):
        self.serializer = ESAddonAutoCompleteSerializer(
            context={'request': self.request})

        obj = self.search()

        with self.assertNumQueries(0):
            result = self.serializer.to_representation(obj)
        return result

    def test_basic(self):
        self.addon = addon_factory()

        result = self.serialize()
        assert set(result.keys()) == set(
            ['id', 'name', 'icon_url', 'type', 'url'])
        assert result['id'] == self.addon.pk
        assert result['name'] == {'en-US': unicode(self.addon.name)}
        assert result['icon_url'] == absolutify(self.addon.get_icon_url(64))
        assert result['type'] == 'extension'
        assert result['url'] == absolutify(self.addon.get_url_path())

    def test_translations(self):
        translated_name = {
            'en-US': u'My Addôn name in english',
            'fr': u'Nom de mon Addôn',
        }
        self.addon = addon_factory()
        self.addon.name = translated_name
        self.addon.save()

        result = self.serialize()
        assert result['name'] == translated_name

        # Try a single translation. The locale activation is normally done by
        # LocaleAndAppURLMiddleware, but since we're directly calling the
        # serializer we need to do it ourselves.
        self.request = APIRequestFactory().get('/', {'lang': 'fr'})
        with override('fr'):
            result = self.serialize()
        assert result['name'] == translated_name['fr']

    def test_icon_url_with_persona_id(self):
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
        assert set(result.keys()) == set(
            ['id', 'name', 'icon_url', 'type', 'url'])
        assert result['type'] == 'persona'
        assert result['icon_url'] == absolutify(self.addon.get_icon_url(64))

    def test_icon_url_persona_with_no_persona_id(self):
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
        assert set(result.keys()) == set(
            ['id', 'name', 'icon_url', 'type', 'url'])
        assert result['type'] == 'persona'
        assert result['icon_url'] == absolutify(self.addon.get_icon_url(64))


class TestAddonDeveloperSerializer(TestBaseUserSerializer):
    serializer_class = AddonDeveloperSerializer

    def test_picture(self):
        serialized = self.serialize()
        assert serialized['picture_url'] is None

        self.user.update(picture_type='image/jpeg')
        serialized = self.serialize()
        assert serialized['picture_url'] == absolutify(self.user.picture_url)
        assert '%s.png' % self.user.id in serialized['picture_url']


class TestReplacementAddonSerializer(TestCase):

    def serialize(self, replacement):
        serializer = ReplacementAddonSerializer()
        return serializer.to_representation(replacement)

    def test_valid_addon_path(self):
        addon = addon_factory(slug=u'stuff', guid=u'newstuff@mozilla')

        rep = ReplacementAddon.objects.create(
            guid='legacy@mozilla', path=u'/addon/stuff/')
        result = self.serialize(rep)
        assert result['guid'] == u'legacy@mozilla'
        assert result['replacement'] == [u'newstuff@mozilla']

        # Edge case, but should accept numeric IDs too
        rep.update(path=u'/addon/%s/' % addon.id)
        result = self.serialize(rep)
        assert result['guid'] == u'legacy@mozilla'
        assert result['replacement'] == [u'newstuff@mozilla']

    def test_invalid_addons(self):
        """Broken paths, invalid add-ons, etc, should fail gracefully to None.
        """
        rep = ReplacementAddon.objects.create(
            guid='legacy@mozilla', path=u'/addon/stuff/')
        result = self.serialize(rep)
        assert result['guid'] == u'legacy@mozilla'
        # Addon path doesn't exist.
        assert result['replacement'] == []

        # Add the add-on but make it not public
        addon = addon_factory(slug=u'stuff', guid=u'newstuff@mozilla',
                              status=amo.STATUS_NULL)
        result = self.serialize(rep)
        assert result['guid'] == u'legacy@mozilla'
        assert result['replacement'] == []

        # Double check that the test is good and it will work once public.
        addon.update(status=amo.STATUS_PUBLIC)
        result = self.serialize(rep)
        assert result['replacement'] == [u'newstuff@mozilla']

        # But urls aren't resolved - and don't break everything
        rep.update(path=absolutify(addon.get_url_path()))
        result = self.serialize(rep)
        assert result['guid'] == u'legacy@mozilla'
        assert result['replacement'] == []

    def test_valid_collection_path(self):
        addon = addon_factory(slug=u'stuff', guid=u'newstuff@mozilla')
        me = user_factory(username=u'me')
        collection = collection_factory(slug=u'bag', author=me)
        collection.add_addon(addon)

        rep = ReplacementAddon.objects.create(
            guid=u'legacy@mozilla', path=u'/collections/me/bag/')
        result = self.serialize(rep)
        assert result['guid'] == u'legacy@mozilla'
        assert result['replacement'] == [u'newstuff@mozilla']

        # Edge case, but should accept numeric user IDs too
        rep.update(path=u'/collections/%s/bag/' % me.id)
        result = self.serialize(rep)
        assert result['guid'] == u'legacy@mozilla'
        assert result['replacement'] == [u'newstuff@mozilla']

    def test_invalid_collections(self):
        """Broken paths, invalid users or collections, should fail gracefully
        to None."""
        rep = ReplacementAddon.objects.create(
            guid=u'legacy@mozilla', path=u'/collections/me/bag/')
        result = self.serialize(rep)
        assert result['guid'] == u'legacy@mozilla'
        assert result['replacement'] == []

        # Create the user but not the collection.
        me = user_factory(username=u'me')
        result = self.serialize(rep)
        assert result['guid'] == u'legacy@mozilla'
        assert result['replacement'] == []

        # Create the collection but make the add-on invalid.
        addon = addon_factory(slug=u'stuff', guid=u'newstuff@mozilla',
                              status=amo.STATUS_NULL)
        collection = collection_factory(slug=u'bag', author=me)
        collection.add_addon(addon)
        result = self.serialize(rep)
        assert result['guid'] == u'legacy@mozilla'
        assert result['replacement'] == []

        # Double check that the test is good and it will work once public.
        addon.update(status=amo.STATUS_PUBLIC)
        result = self.serialize(rep)
        assert result['replacement'] == [u'newstuff@mozilla']


class TestCompatOverrideSerializer(TestCase):

    def serialize(self, override):
        serializer = CompatOverrideSerializer()
        return serializer.to_representation(override)

    def test_linked_addon(self):
        addon = addon_factory(guid='extrabad@thing')
        override = CompatOverride.objects.create(
            name='override with addon', guid=addon.guid, addon=addon)
        CompatOverrideRange.objects.create(
            compat=override, app=amo.FIREFOX.id)
        result = self.serialize(override)

        assert ['addon_guid', 'addon_id', 'name', 'version_ranges'] == sorted(
            result.keys())
        assert result['addon_guid'] == 'extrabad@thing'
        assert result['addon_id'] == addon.id
        assert result['name'] == 'override with addon'
        version_range = {
            'addon_min_version': '0',
            'addon_max_version': '*',
            'applications': [{
                'name': amo.FIREFOX.pretty,
                'id': amo.FIREFOX.id,
                'min_version': '0',
                'max_version': '*',
                'guid': amo.FIREFOX.guid
            }]
        }
        assert result['version_ranges'] == [version_range]

    def test_no_addon(self):
        override = CompatOverride.objects.create(
            name='override', guid='foo@baa')
        CompatOverrideRange.objects.create(
            compat=override, app=amo.FIREFOX.id)
        result = self.serialize(override)

        assert ['addon_guid', 'addon_id', 'name', 'version_ranges'] == sorted(
            result.keys())
        assert result['addon_guid'] == 'foo@baa'
        assert result['addon_id'] is None
        assert result['name'] == 'override'
        version_range = {
            'addon_min_version': '0',
            'addon_max_version': '*',
            'applications': [{
                'name': amo.FIREFOX.pretty,
                'id': amo.FIREFOX.id,
                'min_version': '0',
                'max_version': '*',
                'guid': amo.FIREFOX.guid
            }]
        }
        assert result['version_ranges'] == [version_range]

    def test_multiple_ranges(self):
        override = CompatOverride.objects.create(
            name='override with multiple ranges', guid='foo@baa')
        CompatOverrideRange.objects.create(
            compat=override, app=amo.FIREFOX.id, min_version='23.4',
            max_version='56.7.*')
        CompatOverrideRange.objects.create(
            compat=override, app=amo.THUNDERBIRD.id, min_app_version='1.35',
            max_app_version='90.*')
        result = self.serialize(override)

        assert ['addon_guid', 'addon_id', 'name', 'version_ranges'] == sorted(
            result.keys())
        assert result['addon_guid'] == 'foo@baa'
        assert result['addon_id'] is None
        assert result['name'] == 'override with multiple ranges'
        assert len(result['version_ranges']) == 2
        version_range_firefox = {
            'addon_min_version': '23.4',
            'addon_max_version': '56.7.*',
            'applications': [{
                'name': amo.FIREFOX.pretty,
                'id': amo.FIREFOX.id,
                'min_version': '0',
                'max_version': '*',
                'guid': amo.FIREFOX.guid
            }]
        }
        assert version_range_firefox in result['version_ranges']
        version_range_thunderbird = {
            'addon_min_version': '0',
            'addon_max_version': '*',
            'applications': [{
                'name': amo.THUNDERBIRD.pretty,
                'id': amo.THUNDERBIRD.id,
                'min_version': '1.35',
                'max_version': '90.*',
                'guid': amo.THUNDERBIRD.guid
            }]
        }
        assert version_range_thunderbird in result['version_ranges']

    def test_collapsed_ranges(self):
        """Collapsed ranges are where there is a single version range of
        affected addons, but multiple applications affected."""
        override = CompatOverride.objects.create(
            name='override with single version range', guid='foo@baa')
        CompatOverrideRange.objects.create(
            compat=override, app=amo.FIREFOX.id,
            min_version='23.4', max_version='56.7.*')
        CompatOverrideRange.objects.create(
            compat=override, app=amo.THUNDERBIRD.id,
            min_version='23.4', max_version='56.7.*',
            min_app_version='1.35', max_app_version='90.*')
        result = self.serialize(override)

        assert ['addon_guid', 'addon_id', 'name', 'version_ranges'] == sorted(
            result.keys())
        assert result['addon_guid'] == 'foo@baa'
        assert result['addon_id'] is None
        assert result['name'] == 'override with single version range'
        assert len(result['version_ranges']) == 1
        assert result['version_ranges'][0]['addon_min_version'] == '23.4'
        assert result['version_ranges'][0]['addon_max_version'] == '56.7.*'
        applications = result['version_ranges'][0]['applications']
        assert len(applications) == 2
        application_firefox = {
            'name': amo.FIREFOX.pretty,
            'id': amo.FIREFOX.id,
            'min_version': '0',
            'max_version': '*',
            'guid': amo.FIREFOX.guid
        }
        assert application_firefox in applications
        application_thunderbird = {
            'name': amo.THUNDERBIRD.pretty,
            'id': amo.THUNDERBIRD.id,
            'min_version': '1.35',
            'max_version': '90.*',
            'guid': amo.THUNDERBIRD.guid
        }
        assert application_thunderbird in applications
