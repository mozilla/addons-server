# -*- coding: utf-8 -*-
from django.test.utils import override_settings
from django.utils.translation import override

from rest_framework.test import APIRequestFactory

from olympia import amo
from olympia.accounts.tests.test_serializers import TestBaseUserSerializer
from olympia.addons.models import (
    Addon, AddonCategory, AddonUser, Category, Preview, ReplacementAddon)
from olympia.addons.serializers import (
    AddonBasketSyncSerializer, AddonDeveloperSerializer, AddonSerializer,
    AddonSerializerWithUnlistedData, ESAddonAutoCompleteSerializer,
    ESAddonSerializer, LanguageToolsSerializer, LicenseSerializer,
    ReplacementAddonSerializer, SimpleVersionSerializer, VersionSerializer)
from olympia.addons.utils import generate_addon_guid
from olympia.addons.views import (
    AddonAutoCompleteSearchView, AddonSearchView, AddonViewSet)
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import (
    ESTestCase, TestCase, addon_factory, collection_factory, file_factory,
    user_factory, version_factory)
from olympia.amo.urlresolvers import get_outgoing_url, reverse
from olympia.constants.categories import CATEGORIES
from olympia.constants.licenses import LICENSES_BY_BUILTIN
from olympia.discovery.models import DiscoveryItem
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
            'url': author.get_absolute_url(),
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
            'is_custom': True,
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
        assert result_file['url'] == file_.get_absolute_url(src='')
        assert result_file['permissions'] == file_.webext_permissions_list

        assert data['edit_url'] == absolutify(
            self.addon.get_dev_url(
                'versions.edit', args=[version.pk], prefix_only=True))
        assert data['reviewed'] == version.reviewed
        assert data['version'] == version.version

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
                'release_notes': {
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
            application=amo.ANDROID.id, version='2.0.99')[0]
        av_max = AppVersion.objects.get_or_create(
            application=amo.ANDROID.id, version='3.0.99')[0]
        ApplicationsVersions.objects.get_or_create(
            application=amo.ANDROID.id, version=self.addon.current_version,
            min=av_min, max=av_max)
        # Reset current_version.compatible_apps now that we've added an app.
        del self.addon.current_version._compatible_apps

        cat2 = Category.from_static_category(
            CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION]['alerts-updates'])
        cat2.save()
        AddonCategory.objects.create(addon=self.addon, category=cat2)
        cat3 = Category.from_static_category(
            CATEGORIES[amo.ANDROID.id][amo.ADDON_EXTENSION]['sports-games'])
        cat3.save()
        AddonCategory.objects.create(addon=self.addon, category=cat3)

        result = self.serialize()

        assert result['id'] == self.addon.pk

        assert result['average_daily_users'] == self.addon.average_daily_users
        assert result['categories'] == {
            'firefox': ['alerts-updates', 'bookmarks'],
            'android': ['sports-games']}

        # In this serializer latest_unlisted_version is omitted.
        assert 'latest_unlisted_version' not in result

        assert result['current_version']
        self._test_version(
            self.addon.current_version, result['current_version'])
        self._test_version_license_and_release_notes(
            self.addon.current_version, result['current_version'])

        assert result['authors']
        assert len(result['authors']) == 2
        self._test_author(first_author, result['authors'][0])
        self._test_author(second_author, result['authors'][1])

        utm_string = '&'.join(
            f'{key}={value}'
            for key, value in amo.CONTRIBUTE_UTM_PARAMS.items())
        assert result['contributions_url'] == (
            self.addon.contributions + '?' + utm_string)
        assert result['edit_url'] == absolutify(self.addon.get_dev_url())
        assert result['default_locale'] == self.addon.default_locale
        assert result['description'] == {'en-US': self.addon.description}
        assert result['developer_comments'] == {
            'en-US': self.addon.developer_comments}
        assert result['guid'] == self.addon.guid
        assert result['has_eula'] is False
        assert result['has_privacy_policy'] is False
        assert result['homepage'] == {'en-US': str(self.addon.homepage)}
        assert result['icon_url'] == absolutify(self.addon.get_icon_url(64))
        assert result['icons'] == {
            '32': absolutify(self.addon.get_icon_url(32)),
            '64': absolutify(self.addon.get_icon_url(64)),
            '128': absolutify(self.addon.get_icon_url(128)),
        }
        assert result['is_disabled'] == self.addon.is_disabled
        assert result['is_experimental'] == self.addon.is_experimental is False
        assert result['is_recommended'] == self.addon.is_recommended is False
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
        assert result['support_url'] == {'en-US': str(self.addon.support_url)}
        assert set(result['tags']) == {'some_tag', 'some_other_tag'}
        assert result['type'] == 'extension'
        assert result['url'] == self.addon.get_absolute_url()
        assert result['weekly_downloads'] == self.addon.weekly_downloads

        return result

    def test_wrap_outgoing_links(self):
        self.addon = addon_factory(
            contributions=u'https://paypal.me/fôobar',
            homepage='http://support.example.com/',
            support_url=u'https://support.example.org/support/my-âddon/')
        self.request = APIRequestFactory().get('/', {'wrap_outgoing_links': 1})
        result = self.serialize()
        utm_string = '&'.join(
            f'{key}={value}'
            for key, value in amo.CONTRIBUTE_UTM_PARAMS.items())
        assert result['contributions_url'] == get_outgoing_url(
            str(self.addon.contributions) + '?' + utm_string)
        assert result['homepage'] == {
            'en-US': get_outgoing_url(str(self.addon.homepage)),
        }
        assert result['support_url'] == {
            'en-US': get_outgoing_url(str(self.addon.support_url)),
        }

        # Try a single translation.
        self.request = APIRequestFactory().get('/', {
            'lang': 'en-US', 'wrap_outgoing_links': 1})
        result = self.serialize()
        assert result['contributions_url'] == get_outgoing_url(
            str(self.addon.contributions) + '?' + utm_string)
        assert result['homepage'] == {
            'en-US': get_outgoing_url(str(self.addon.homepage)),
        }
        assert result['support_url'] == {
            'en-US': get_outgoing_url(str(self.addon.support_url)),
        }
        # And again, but with v3 style flat strings
        gates = {None: ('l10n_flat_input_output',)}
        with override_settings(DRF_API_GATES=gates):
            result = self.serialize()
        assert result['contributions_url'] == get_outgoing_url(
            str(self.addon.contributions) + '?' + utm_string)
        assert result['homepage'] == (
            get_outgoing_url(str(self.addon.homepage))
        )
        assert result['support_url'] == (
            get_outgoing_url(str(self.addon.support_url))
        )

        # Try with empty strings/None. Annoyingly, contribution model field
        # does not let us set it to None, so use a translated field for that
        # part of the test.
        self.addon.update(contributions='', homepage=None)
        result = self.serialize()
        assert result['contributions_url'] == ''
        assert result['homepage'] is None

        # Check the contribute utm parameters are added correctly when the url
        # already has query parameters.
        self.addon.update(contributions='https://paypal.me/has?query=params')
        result = self.serialize()
        assert result['contributions_url'] == get_outgoing_url(
            str(self.addon.contributions) + '&' + utm_string)

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

    def test_is_disabled(self):
        self.addon = addon_factory(disabled_by_user=True)
        result = self.serialize()

        assert result['is_disabled'] is True

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
            '64': absolutify(self.addon.get_icon_url(64)),
            '128': absolutify(self.addon.get_icon_url(128)),
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
        # As we've dropped featuring, we're faking it with recommended status
        DiscoveryItem.objects.create(addon=self.addon, recommendable=True)
        result = self.serialize()

        assert 'is_featured' not in result

        # It's only present in v3
        gates = {None: ('is-featured-addon-shim',)}
        with override_settings(DRF_API_GATES=gates):
            result = self.serialize()
            assert result['is_featured'] is False
            self.addon.current_version.update(recommendation_approved=True)
            result = self.serialize()
            assert result['is_featured'] is True

    def test_is_recommended(self):
        self.addon = addon_factory()
        DiscoveryItem.objects.create(addon=self.addon, recommendable=True)
        self.addon.current_version.update(recommendation_approved=True)
        assert self.addon.is_recommended

        result = self.serialize()
        assert result['is_recommended'] is True

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
        assert result['description'] == {'fr': translated_descriptions['fr']}
        assert result['homepage'] == {'fr': translated_homepages['fr']}

        # And again, but with v3 style flat strings
        with override('fr'):
            gates = {None: ('l10n_flat_input_output',)}
            with override_settings(DRF_API_GATES=gates):
                result = self.serialize()
        assert result['description'] == translated_descriptions['fr']
        assert result['homepage'] == translated_homepages['fr']

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

        # Test with no compatibility info.
        file_ = self.addon.current_version.all_files[0]
        file_.update(strict_compatibility=False)
        ApplicationsVersions.objects.filter(
            version=self.addon.current_version).delete()

        result_version = self.serialize()['current_version']
        assert result_version['is_strict_compatibility_enabled'] is False
        assert result_version['compatibility'] == {}

        # Test with some compatibility info but that should be ignored because
        # its type is in NO_COMPAT.
        self.addon.update(type=amo.ADDON_SEARCH)
        result_version = self.serialize()['current_version']
        assert result_version['compatibility'] == {
            'android': {'max': '65535', 'min': '11.0'},
            'firefox': {'max': '65535', 'min': '4.0'},
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

    def test_created(self):
        self.addon = addon_factory()
        result = self.serialize()

        assert result['created'] == (
            self.addon.created.replace(microsecond=0).isoformat() + 'Z')

        # And to make sure it's not present in v3
        gates = {None: ('del-addons-created-field',)}
        with override_settings(DRF_API_GATES=gates):
            result = self.serialize()
            assert 'created' not in result


class TestAddonSerializerOutput(AddonSerializerOutputTestMixin, TestCase):
    serializer_class = AddonSerializer

    def setUp(self):
        super(TestAddonSerializerOutput, self).setUp()
        self.action = 'retrieve'

    def serialize(self):
        self.serializer = self.serializer_class(context={
            'request': self.request,
            'view': AddonViewSet(action=self.action)
        })
        # Manually reload the add-on first to clear any cached properties.
        self.addon = Addon.unfiltered.get(pk=self.addon.pk)
        return self.serializer.to_representation(self.addon)

    def test_langpack_current_version_with_appversion(self):
        """Test for langpack current_version property when appversion param
        is passed. Specific to the non-ES serializer, this option is only
        available through the add-on detail API.
        """
        self.addon = addon_factory(
            type=amo.ADDON_LPAPP, target_locale='es',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'})
        self.addon.current_version.update(created=self.days_ago(3))
        version_for_58 = version_factory(
            addon=self.addon,
            file_kw={'strict_compatibility': True},
            min_app_version='58.0', max_app_version='58.*')
        version_for_58.update(created=self.days_ago(2))
        # Extra version for 59, should not be returned.
        version_factory(
            addon=self.addon,
            file_kw={'strict_compatibility': True},
            min_app_version='59.0', max_app_version='59.*')
        # Extra version that would be compatible and more recent, but belongs
        # to a different add-on and should be ignored.
        addon_factory(
            type=amo.ADDON_LPAPP, target_locale='fr',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '58.0', 'max_app_version': '58.*'})
        # Extra version that would be compatible and more recent, but is not
        # public.
        not_public_version_for_58 = version_factory(
            addon=self.addon,
            file_kw={'strict_compatibility': True,
                     'status': amo.STATUS_DISABLED},
            min_app_version='58.0', max_app_version='58.*')
        not_public_version_for_58.update(created=self.days_ago(1))

        self.request = APIRequestFactory().get('/?app=firefox&appversion=58.0')
        self.action = 'retrieve'

        result = self.serialize()
        assert result['current_version']['id'] == version_for_58.pk
        assert result['current_version']['compatibility'] == {
            'firefox': {'max': u'58.*', 'min': u'58.0'}
        }
        assert result['current_version']['is_strict_compatibility_enabled']

    def test_langpack_current_version_with_appversion_fallback(self):
        """Like test_langpack_current_version_with_appversion() above, but
        falling back to the current_version because no compatible version was
        found."""
        self.addon = addon_factory(
            type=amo.ADDON_LPAPP, target_locale='es',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'})
        self.addon.current_version.update(created=self.days_ago(2))
        version_factory(
            addon=self.addon,
            file_kw={'strict_compatibility': True},
            min_app_version='59.0', max_app_version='59.*')
        self.request = APIRequestFactory().get('/?app=firefox&appversion=58.0')
        self.action = 'retrieve'

        result = self.serialize()
        assert result['current_version']['id'] == self.addon.current_version.pk
        assert result['current_version']['compatibility'] == {
            'firefox': {'max': u'59.*', 'min': u'59.0'}
        }
        assert result['current_version']['is_strict_compatibility_enabled']

    def test_langpack_current_version_without_parameters(self):
        self.addon = addon_factory(
            type=amo.ADDON_LPAPP, target_locale='es',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'})
        self.addon.current_version.update(created=self.days_ago(2))
        version_for_58 = version_factory(
            addon=self.addon,
            file_kw={'strict_compatibility': True},
            min_app_version='58.0', max_app_version='58.*')
        version_for_58.update(created=self.days_ago(1))
        version_factory(
            addon=self.addon,
            file_kw={'strict_compatibility': True},
            min_app_version='59.0', max_app_version='59.*')
        # Regular detail action with no special parameters, we'll just return
        # the current_version.
        self.action = 'retrieve'

        result = self.serialize()
        assert result['current_version']['id'] == self.addon.current_version.pk
        assert result['current_version']['compatibility'] == {
            'firefox': {'max': u'59.*', 'min': u'59.0'}
        }
        assert result['current_version']['is_strict_compatibility_enabled']

    def test_langpack_current_version_with_non_detail_action(self):
        self.addon = addon_factory(
            type=amo.ADDON_LPAPP, target_locale='es',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'})
        self.addon.current_version.update(created=self.days_ago(2))
        version_for_58 = version_factory(
            addon=self.addon,
            file_kw={'strict_compatibility': True},
            min_app_version='58.0', max_app_version='58.*')
        version_for_58.update(created=self.days_ago(1))
        version_factory(
            addon=self.addon,
            file_kw={'strict_compatibility': True},
            min_app_version='59.0', max_app_version='59.*')
        # The parameters are going to be ignored, since we're not dealing with
        # the detail API.
        self.request = APIRequestFactory().get('/?app=firefox&appversion=58.0')
        self.action = 'list'

        result = self.serialize()
        assert result['current_version']['id'] == self.addon.current_version.pk
        assert result['current_version']['compatibility'] == {
            'firefox': {'max': u'59.*', 'min': u'59.0'}
        }
        assert result['current_version']['is_strict_compatibility_enabled']

    def test_app_and_appversion_parameters_on_non_langpack(self):
        self.addon = addon_factory(
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'})
        self.addon.current_version.update(created=self.days_ago(2))
        version_for_58 = version_factory(
            addon=self.addon,
            file_kw={'strict_compatibility': True},
            min_app_version='58.0', max_app_version='58.*')
        version_for_58.update(created=self.days_ago(1))
        # Extra version for 59, should not be returned.
        version_factory(
            addon=self.addon,
            file_kw={'strict_compatibility': True},
            min_app_version='59.0', max_app_version='59.*')
        # The parameters are going to be ignored since it's not a langpack.
        self.request = APIRequestFactory().get('/?app=firefox&appversion=58.0')
        self.action = 'retrieve'

        result = self.serialize()
        assert result['current_version']['id'] == self.addon.current_version.pk
        assert result['current_version']['compatibility'] == {
            'firefox': {'max': u'59.*', 'min': u'59.0'}
        }
        assert result['current_version']['is_strict_compatibility_enabled']

    def test_latest_unlisted_version_with_right_serializer(self):
        self.serializer_class = AddonSerializerWithUnlistedData

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


class TestESAddonSerializerOutput(AddonSerializerOutputTestMixin, ESTestCase):
    serializer_class = ESAddonSerializer

    def tearDown(self):
        super(TestESAddonSerializerOutput, self).tearDown()
        self.empty_index('default')
        self.refresh()

    def search(self):
        self.reindex(Addon)

        view = AddonSearchView()
        view.request = self.request
        qs = view.get_queryset()

        # We don't even filter - there should only be one addon in the index
        # at this point, and that allows us to get a constant score that we
        # can test for in test_score()
        return qs.execute()[0]

    def serialize(self):
        self.serializer = self.serializer_class(context={
            'request': self.request,
            'view': AddonSearchView(action='list')
        })

        obj = self.search()

        with self.assertNumQueries(0):
            result = self.serializer.to_representation(obj)
        return result

    def _test_author(self, author, data):
        """Override because the ES serializer doesn't include picture_url."""
        assert data == {
            'id': author.pk,
            'name': author.name,
            'url': author.get_absolute_url(),
            'username': author.username,
        }

    def test_score(self):
        self.request.version = 'v4'
        self.addon = addon_factory()
        result = self.serialize()
        assert result['_score'] == 1.0  # No query, we get ConstantScoring(1.0)

    def test_no_score_in_v3(self):
        self.request.version = 'v3'
        self.addon = addon_factory()
        result = self.serialize()
        assert '_score' not in result


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
                'release_notes': {
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
        assert result['files'][0]['url'] == first_file.get_absolute_url(src='')

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
        assert result['files'][1]['url'] == second_file.get_absolute_url(
            src='')

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
            'is_custom': True,
            'name': {'en-US': u'My License', 'fr': u'Mä Licence'},
            'text': {
                'en-US': u'Lorem ipsum dolor sit amet, has nemore patrioqué',
            },
            'url': 'http://license.example.com/',
        }
        assert result['reviewed'] == (
            now.replace(microsecond=0).isoformat() + 'Z')

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
        assert result['license']['is_custom'] is True
        assert result['license']['url'] == absolutify(
            self.version.license_url())

        # And make sure it's not present in v3
        gates = {None: ('del-version-license-is-custom',)}
        with override_settings(DRF_API_GATES=gates):
            result = self.serialize()
            assert 'is_custom' not in result['license']

        license.update(builtin=1)
        result = self.serialize()
        # Builtin licenses with no url shouldn't get the version license url.
        assert result['license']['url'] is None
        assert result['license']['is_custom'] is False

        # Again, make sure it's not present in v3
        gates = {None: ('del-version-license-is-custom',)}
        with override_settings(DRF_API_GATES=gates):
            result = self.serialize()
            assert 'is_custom' not in result['license']

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
        assert result['is_custom'] is False
        # A request with no ?lang gets you the site default l10n in a dict to
        # match how non-constant values are returned.
        assert result['name'] == {
            'en-US': str(LICENSES_BY_BUILTIN[18].name)}

        accept_request = APIRequestFactory().get('/')
        accept_request.LANG = 'de'
        result = LicenseSerializer(
            context={'request': accept_request}).to_representation(license)
        # An Accept-Language should result in a different default though.
        assert result['name'] == {
            'de': str(LICENSES_BY_BUILTIN[18].name)}

        # But a requested lang returns a flat string
        lang_request = APIRequestFactory().get('/?lang=fr')
        result = LicenseSerializer(
            context={'request': lang_request}).to_representation(license)
        assert result['name'] == str(LICENSES_BY_BUILTIN[18].name)

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
            type=amo.ADDON_LPAPP, target_locale='fr')
        result = self.serialize()
        assert result['id'] == self.addon.pk
        assert result['default_locale'] == self.addon.default_locale
        assert result['guid'] == self.addon.guid
        assert result['name'] == {'en-US': self.addon.name}
        assert result['slug'] == self.addon.slug
        assert result['target_locale'] == self.addon.target_locale
        assert result['type'] == 'language'
        assert result['url'] == self.addon.get_absolute_url()
        assert 'current_compatible_version' not in result
        assert 'locale_disambiguation' not in result

    @override_settings(
        DRF_API_GATES={None: ('addons-locale_disambiguation-shim',)})
    def test_locale_disambiguation_in_v3(self):
        self.addon = addon_factory(
            type=amo.ADDON_LPAPP, target_locale='fr')
        result = self.serialize()
        assert result['locale_disambiguation'] is None

    def test_basic_dict(self):
        self.addon = addon_factory(type=amo.ADDON_DICT)
        result = self.serialize()
        assert result['type'] == 'dictionary'
        assert 'current_compatible_version' not in result

    def test_current_compatible_version(self):
        # Set a filename to make sure the file actually exists.
        # file_factory (used via addon_factory) copies files that exists
        # as fixtures in src/olympia/files/fixtures/files to their rightful
        # place.
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
        assert (
            set(result['current_compatible_version'].keys()) ==
            {'id', 'files', 'reviewed', 'version'}
        )

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
        assert (
            set(result.keys()) ==
            {'id', 'name', 'icon_url', 'is_recommended', 'type', 'url'}
        )
        assert result['id'] == self.addon.pk
        assert result['name'] == {'en-US': str(self.addon.name)}
        assert result['icon_url'] == absolutify(self.addon.get_icon_url(64))
        assert result['is_recommended'] == self.addon.is_recommended is False
        assert result['type'] == 'extension'
        assert result['url'] == self.addon.get_absolute_url()

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
        assert result['name'] == {'fr': translated_name['fr']}

        # And again, but with v3 style flat strings
        with override('fr'):
            gates = {None: ('l10n_flat_input_output',)}
            with override_settings(DRF_API_GATES=gates):
                result = self.serialize()
        assert result['name'] == translated_name['fr']


class TestAddonDeveloperSerializer(TestBaseUserSerializer):
    serializer_class = AddonDeveloperSerializer

    def test_picture(self):
        serialized = self.serialize()
        assert serialized['picture_url'] is None

        self.user.update(picture_type='image/jpeg')
        serialized = self.serialize()
        assert serialized['picture_url'] == absolutify(self.user.picture_url)
        assert '%s.png' % self.user.id in serialized['picture_url']


class TestAddonBasketSyncSerializer(TestCase):
    def serialize(self):
        serializer = AddonBasketSyncSerializer(self.addon)
        return serializer.to_representation(self.addon)

    def test_basic(self):
        category = Category.from_static_category(
            CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION]['bookmarks'])
        category.save()
        self.addon = addon_factory(category=category)
        data = self.serialize()
        expected_data = {
            'authors': [],
            'average_daily_users': self.addon.average_daily_users,
            'categories': {'firefox': ['bookmarks']},
            'current_version': {
                'id': self.addon.current_version.pk,
                'compatibility': {
                    'firefox': {
                        'min': '4.0.99',
                        'max': '5.0.99',
                    }
                },
                'is_strict_compatibility_enabled': False,
                'version': self.addon.current_version.version,
            },
            'default_locale': 'en-US',
            'guid': self.addon.guid,
            'id': self.addon.pk,
            'is_disabled': self.addon.is_disabled,
            'is_recommended': self.addon.is_recommended,
            'last_updated': self.addon.last_updated.replace(
                microsecond=0).isoformat() + 'Z',
            'latest_unlisted_version': None,
            'name': str(self.addon.name),  # No translations.
            'ratings': {
                'average': 0.0,
                'bayesian_average': 0.0,
                'count': 0,
                'text_count': 0
            },
            'slug': self.addon.slug,
            'status': 'public',
            'type': 'extension'
        }
        assert expected_data == data

    def test_with_unlisted_version(self):
        self.addon = addon_factory()
        version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        data = self.serialize()
        assert data['latest_unlisted_version'] == {
            'id': version.pk,
            'compatibility': {
                'firefox': {
                    'min': '4.0.99',
                    'max': '5.0.99',
                }
            },
            'is_strict_compatibility_enabled': False,
            'version': version.version,
        }

    def test_non_listed_author(self):
        self.addon = addon_factory()
        user1 = user_factory()
        user2 = user_factory()
        AddonUser.objects.create(
            addon=self.addon, user=user1, listed=True,
            role=amo.AUTHOR_ROLE_OWNER, position=1)
        AddonUser.objects.create(
            addon=self.addon, user=user2, listed=False,
            role=amo.AUTHOR_ROLE_DEV, position=2)
        data = self.serialize()
        assert data['authors'] == [{
            'id': user1.pk,
            'deleted': False,
            'display_name': '',
            'email': user1.email,
            'homepage': user1.homepage,
            'last_login': user1.last_login,
            'location': user1.location
        }, {
            'id': user2.pk,
            'deleted': False,
            'display_name': '',
            'email': user2.email,
            'homepage': user2.homepage,
            'last_login': user2.last_login,
            'location': user2.location
        }]


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
        addon.update(status=amo.STATUS_APPROVED)
        result = self.serialize(rep)
        assert result['replacement'] == [u'newstuff@mozilla']

        # But urls aren't resolved - and don't break everything
        rep.update(path=addon.get_absolute_url())
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
        addon.update(status=amo.STATUS_APPROVED)
        result = self.serialize(rep)
        assert result['replacement'] == [u'newstuff@mozilla']
