import io
import json
import mimetypes
import os
import stat
import tarfile
import tempfile
import zipfile
from collections import Counter, OrderedDict
from datetime import datetime, timedelta
from unittest import mock
from unittest.mock import patch
from urllib.parse import unquote

from django.conf import settings
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.utils import override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode

import pytest
from elasticsearch import Elasticsearch
from freezegun import freeze_time
from rest_framework.exceptions import ErrorDetail
from rest_framework.test import APIRequestFactory
from waffle import switch_is_active
from waffle.testutils import override_switch

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import (
    APITestClientJWT,
    APITestClientSessionID,
    ESTestCase,
    TestCase,
    addon_factory,
    collection_factory,
    reverse_ns,
    user_factory,
    version_factory,
)
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.urlresolvers import get_outgoing_url
from olympia.bandwagon.models import CollectionAddon
from olympia.constants.browsers import CHROME
from olympia.constants.categories import CATEGORIES, CATEGORIES_BY_ID
from olympia.constants.licenses import LICENSE_GPL3
from olympia.constants.promoted import (
    LINE,
    RECOMMENDED,
    SPONSORED,
    SPOTLIGHT,
    STRATEGIC,
    VERIFIED,
)
from olympia.files.tests.test_models import UploadMixin
from olympia.files.utils import parse_addon, parse_xpi
from olympia.ratings.models import Rating
from olympia.reviewers.models import AutoApprovalSummary
from olympia.search.utils import get_es
from olympia.tags.models import Tag
from olympia.translations.models import Translation
from olympia.users.models import EmailUserRestriction, UserProfile
from olympia.versions.models import (
    ApplicationsVersions,
    AppVersion,
    License,
    VersionPreview,
    VersionProvenance,
    VersionReviewerFlags,
)

from ..models import (
    Addon,
    AddonApprovalsCounter,
    AddonBrowserMapping,
    AddonCategory,
    AddonRegionalRestrictions,
    AddonUser,
    AddonUserPendingConfirmation,
    DeniedSlug,
    Preview,
    ReplacementAddon,
)
from ..serializers import (
    AddonAuthorSerializer,
    AddonPendingAuthorSerializer,
    CompactLicenseSerializer,
    DeveloperAddonSerializer,
    DeveloperVersionSerializer,
    LicenseSerializer,
)
from ..utils import DeleteTokenSigner, generate_addon_guid
from ..views import (
    DEFAULT_FIND_REPLACEMENT_PATH,
    FIND_REPLACEMENT_SRC,
    AddonAutoCompleteSearchView,
    AddonSearchView,
)


def _get_upload(filename):
    return SimpleUploadedFile(
        filename,
        open(get_image_path(filename), 'rb').read(),
        content_type=mimetypes.guess_type(filename)[0],
    )


class TestStatus(TestCase):
    client_class = APITestClientSessionID
    fixtures = ['base/addon_3615']

    def setUp(self):
        super().setUp()
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version
        self.file = self.version.file
        assert self.addon.status == amo.STATUS_APPROVED
        self.url = reverse_ns(
            'addon-detail', api_version='v5', kwargs={'pk': self.addon.pk}
        )

    def test_incomplete(self):
        self.addon.update(status=amo.STATUS_NULL)
        assert self.client.get(self.url).status_code == 401

    def test_nominated(self):
        self.addon.update(status=amo.STATUS_NOMINATED)
        assert self.client.get(self.url).status_code == 401

    def test_public(self):
        self.addon.update(status=amo.STATUS_APPROVED)
        assert self.client.get(self.url).status_code == 200

    def test_deleted(self):
        self.addon.update(status=amo.STATUS_DELETED)
        assert self.client.get(self.url).status_code == 404

    def test_disabled(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.client.get(self.url).status_code == 401

    def test_disabled_by_user(self):
        self.addon.update(disabled_by_user=True)
        assert self.client.get(self.url).status_code == 401


class TestFindReplacement(TestCase):
    def test_no_match(self):
        self.url = reverse('addons.find_replacement') + '?guid=xxx'
        response = self.client.get(self.url)
        self.assert3xx(
            response,
            (
                DEFAULT_FIND_REPLACEMENT_PATH + '?utm_source=addons.mozilla.org'
                '&utm_medium=referral&utm_content=%s' % FIND_REPLACEMENT_SRC
            ),
        )

    def test_match(self):
        addon_factory(slug='replacey')
        ReplacementAddon.objects.create(guid='xxx', path='/addon/replacey/')
        self.url = reverse('addons.find_replacement') + '?guid=xxx'
        response = self.client.get(self.url)
        self.assert3xx(
            response,
            (
                '/addon/replacey/?utm_source=addons.mozilla.org'
                + '&utm_medium=referral&utm_content=%s' % FIND_REPLACEMENT_SRC
            ),
        )

    def test_match_no_leading_slash(self):
        addon_factory(slug='replacey')
        ReplacementAddon.objects.create(guid='xxx', path='addon/replacey/')
        self.url = reverse('addons.find_replacement') + '?guid=xxx'
        response = self.client.get(self.url)
        self.assert3xx(
            response,
            (
                '/addon/replacey/?utm_source=addons.mozilla.org'
                + '&utm_medium=referral&utm_content=%s' % FIND_REPLACEMENT_SRC
            ),
        )

    def test_no_guid_param_is_404(self):
        self.url = reverse('addons.find_replacement')
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_external_url(self):
        ReplacementAddon.objects.create(guid='xxx', path='https://mozilla.org/')
        self.url = reverse('addons.find_replacement') + '?guid=xxx'
        response = self.client.get(self.url)
        self.assert3xx(response, get_outgoing_url('https://mozilla.org/'))


class AddonAndVersionViewSetDetailMixin:
    """Tests that play with addon state and permissions. Shared between addon
    and version viewset detail tests since both need to react the same way."""

    def _test_url(self):
        raise NotImplementedError

    def _set_tested_url(self, param):
        raise NotImplementedError

    def test_get_by_id(self):
        self._test_url()

    def test_get_by_slug(self):
        self._set_tested_url(self.addon.slug)
        self._test_url()

    def test_get_by_guid(self):
        self._set_tested_url(self.addon.guid)
        self._test_url()

    def test_get_by_guid_uppercase(self):
        self._set_tested_url(self.addon.guid.upper())
        self._test_url()

    def test_get_by_guid_email_format(self):
        self.addon.update(guid='my-addon@example.tld')
        self._set_tested_url(self.addon.guid)
        self._test_url()

    def test_get_by_guid_email_short_format(self):
        self.addon.update(guid='@example.tld')
        self._set_tested_url(self.addon.guid)
        self._test_url()

    def test_get_by_guid_email_really_short_format(self):
        self.addon.update(guid='@example')
        self._set_tested_url(self.addon.guid)
        self._test_url()

    def test_get_not_public_anonymous(self):
        self.addon.update(status=amo.STATUS_NOMINATED)
        response = self.client.get(self.url)
        assert response.status_code == 401
        data = json.loads(force_str(response.content))
        assert data['detail'] == ('Authentication credentials were not provided.')
        assert data['is_disabled_by_developer'] is False
        assert data['is_disabled_by_mozilla'] is False

    def test_get_not_public_no_rights(self):
        self.addon.update(status=amo.STATUS_NOMINATED)
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403
        data = json.loads(force_str(response.content))
        assert data['detail'] == ('You do not have permission to perform this action.')
        assert data['is_disabled_by_developer'] is False
        assert data['is_disabled_by_mozilla'] is False

    def test_get_not_public_reviewer(self):
        self.addon.update(status=amo.STATUS_NOMINATED)
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_not_public_author(self):
        self.addon.update(status=amo.STATUS_NOMINATED)
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_disabled_by_user_anonymous(self):
        self.addon.update(disabled_by_user=True)
        response = self.client.get(self.url)
        assert response.status_code == 401
        data = json.loads(force_str(response.content))
        assert data['detail'] == ('Authentication credentials were not provided.')
        assert data['is_disabled_by_developer'] is True
        assert data['is_disabled_by_mozilla'] is False

    def test_get_disabled_by_user_other_user(self):
        self.addon.update(disabled_by_user=True)
        user = UserProfile.objects.create(username='someone')
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403
        data = json.loads(force_str(response.content))
        assert data['detail'] == ('You do not have permission to perform this action.')
        assert data['is_disabled_by_developer'] is True
        assert data['is_disabled_by_mozilla'] is False

    def test_disabled_by_admin_anonymous(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        response = self.client.get(self.url)
        assert response.status_code == 401
        data = json.loads(force_str(response.content))
        assert data['detail'] == ('Authentication credentials were not provided.')
        assert data['is_disabled_by_developer'] is False
        assert data['is_disabled_by_mozilla'] is True

    def test_disabled_by_admin_no_rights(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        user = UserProfile.objects.create(username='someone')
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403
        data = json.loads(force_str(response.content))
        assert data['detail'] == ('You do not have permission to perform this action.')
        assert data['is_disabled_by_developer'] is False
        assert data['is_disabled_by_mozilla'] is True

    def test_get_not_listed(self):
        self.make_addon_unlisted(self.addon)
        response = self.client.get(self.url)
        assert response.status_code == 401
        data = json.loads(force_str(response.content))
        assert data['detail'] == ('Authentication credentials were not provided.')
        assert data['is_disabled_by_developer'] is False
        assert data['is_disabled_by_mozilla'] is False

        AddonRegionalRestrictions.objects.filter(addon=self.addon).update(
            excluded_regions=['AB', 'CD', 'FR']
        )
        # Regional restrictions should be processed after other permission handling, so
        # something that would return a 401/403/404 without region restrictions would
        # still do that.
        response = self.client.get(self.url, HTTP_X_COUNTRY_CODE='fr')
        assert response.status_code == 401
        # Response is short enough that it won't be compressed, so it doesn't
        # depend on Accept-Encoding.
        assert response['Vary'] == 'origin, X-Country-Code, Accept-Language'

    def test_get_not_listed_no_rights(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.make_addon_unlisted(self.addon)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403
        data = json.loads(force_str(response.content))
        assert data['detail'] == ('You do not have permission to perform this action.')
        assert data['is_disabled_by_developer'] is False
        assert data['is_disabled_by_mozilla'] is False

        AddonRegionalRestrictions.objects.filter(addon=self.addon).update(
            excluded_regions=['AB', 'CD', 'FR']
        )
        # Regional restrictions should be processed after other permission handling, so
        # something that would return a 401/403/404 without region restrictions would
        # still do that.
        response = self.client.get(self.url, HTTP_X_COUNTRY_CODE='fr')
        assert response.status_code == 403
        # Response is short enough that it won't be compressed, so it doesn't
        # depend on Accept-Encoding.
        assert response['Vary'] == 'origin, X-Country-Code, Accept-Language'

    def test_get_not_listed_simple_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.make_addon_unlisted(self.addon)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403
        data = json.loads(force_str(response.content))
        assert data['detail'] == ('You do not have permission to perform this action.')
        assert data['is_disabled_by_developer'] is False
        assert data['is_disabled_by_mozilla'] is False

    def test_get_not_listed_specific_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.make_addon_unlisted(self.addon)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_not_listed_unlisted_viewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'ReviewerTools:ViewUnlisted')
        self.make_addon_unlisted(self.addon)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_not_listed_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.make_addon_unlisted(self.addon)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_deleted(self):
        self.addon.delete()
        response = self.client.get(self.url)
        assert response.status_code == 404
        data = json.loads(force_str(response.content))
        assert data['detail'] == 'Not found.'
        # `is_disabled_by_developer` and `is_disabled_by_mozilla` are only
        # added for 401/403.
        assert 'is_disabled_by_developer' not in data
        assert 'is_disabled_by_mozilla' not in data

    def test_get_deleted_no_rights(self):
        self.addon.delete()
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 404
        data = json.loads(force_str(response.content))
        assert data['detail'] == 'Not found.'
        # `is_disabled_by_developer` and `is_disabled_by_mozilla` are only
        # added for 401/403.
        assert 'is_disabled_by_developer' not in data
        assert 'is_disabled_by_mozilla' not in data

    def test_get_deleted_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.addon.delete()
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 404
        data = json.loads(force_str(response.content))
        assert data['detail'] == 'Not found.'
        # `is_disabled_by_developer` and `is_disabled_by_mozilla` are only
        # added for 401/403.
        assert 'is_disabled_by_developer' not in data
        assert 'is_disabled_by_mozilla' not in data

    def test_get_deleted_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, 'Addons:ViewDeleted,Addons:Review')
        self.addon.delete()
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_deleted_author(self):
        # Owners can't see their own add-on once deleted, only admins can.
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.addon.delete()
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 404
        data = json.loads(force_str(response.content))
        assert data['detail'] == 'Not found.'
        # `is_disabled_by_developer` and `is_disabled_by_mozilla` are only
        # added for 401/403.
        assert 'is_disabled_by_developer' not in data
        assert 'is_disabled_by_mozilla' not in data

    def test_get_addon_not_found(self):
        self._set_tested_url(self.addon.pk + 42)
        response = self.client.get(self.url)
        assert response.status_code == 404
        data = json.loads(force_str(response.content))
        assert data['detail'] == 'Not found.'
        # `is_disabled_by_developer` and `is_disabled_by_mozilla` are only
        # added for 401/403.
        assert 'is_disabled_by_developer' not in data
        assert 'is_disabled_by_mozilla' not in data

        AddonRegionalRestrictions.objects.filter(addon=self.addon).update(
            excluded_regions=['AB', 'CD', 'FR']
        )
        # Regional restrictions should be processed after other permission handling, so
        # something that would return a 401/403/404 without region restrictions would
        # still do that.
        response = self.client.get(self.url, HTTP_X_COUNTRY_CODE='fr')
        assert response.status_code == 404
        # Response is short enough that it won't be compressed, so it doesn't
        # depend on Accept-Encoding.
        assert response['Vary'] == 'origin, X-Country-Code, Accept-Language'

    def test_addon_regional_restrictions(self):
        response = self.client.get(
            self.url, {'lang': 'en-US'}, HTTP_X_COUNTRY_CODE='fr'
        )
        assert response.status_code == 200
        assert (
            response['Vary']
            == 'origin, Accept-Encoding, X-Country-Code, Accept-Language'
        )

        AddonRegionalRestrictions.objects.create(
            addon=self.addon, excluded_regions=['AB', 'CD']
        )
        response = self.client.get(
            self.url, {'lang': 'en-US'}, HTTP_X_COUNTRY_CODE='fr'
        )
        assert response.status_code == 200
        assert (
            response['Vary']
            == 'origin, Accept-Encoding, X-Country-Code, Accept-Language'
        )

        AddonRegionalRestrictions.objects.filter(addon=self.addon).update(
            excluded_regions=['AB', 'CD', 'FR']
        )
        response = self.client.get(
            self.url, data={'lang': 'en-US'}, HTTP_X_COUNTRY_CODE='fr'
        )
        assert response.status_code == 451
        # Response is short enough that it won't be compressed, so it doesn't
        # depend on Accept-Encoding.
        assert response['Vary'] == 'origin, X-Country-Code, Accept-Language'
        assert response['Link'] == (
            '<https://www.mozilla.org/about/policy/transparency/>; rel="blocked-by"'
        )
        data = response.json()
        assert data == {'detail': 'Unavailable for legal reasons.'}

        # But admins can still access:
        user = user_factory()
        self.grant_permission(user, 'Addons:Edit')
        self.client.login_api(user)
        response = self.client.get(
            self.url, data={'lang': 'en-US'}, HTTP_X_COUNTRY_CODE='fr'
        )
        assert response.status_code == 200


class TestAddonViewSetDetail(AddonAndVersionViewSetDetailMixin, TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        super().setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(), name='My Addôn', slug='my-addon'
        )
        self._set_tested_url(self.addon.pk)

    def _test_url(self, extra=None, **kwargs):
        if extra is None:
            extra = {}
        response = self.client.get(self.url, data=kwargs, **extra)
        assert response.status_code == 200
        result = json.loads(force_str(response.content))
        assert (
            response['Vary']
            == 'origin, Accept-Encoding, X-Country-Code, Accept-Language'
        )
        assert result['id'] == self.addon.pk
        assert result['name'] == {'en-US': 'My Addôn'}
        assert result['slug'] == self.addon.slug
        assert result['last_updated'] == (
            self.addon.last_updated.replace(microsecond=0).isoformat() + 'Z'
        )
        return result

    def _set_tested_url(self, param):
        self.url = reverse_ns('addon-detail', api_version='v5', kwargs={'pk': param})

    def test_queries(self):
        with self.assertNumQueries(15):
            # 15 queries:
            # - 2 savepoints because of tests
            # - 1 for the add-on
            # - 1 for its translations
            # - 1 for its categories
            # - 1 for its current_version and file
            # - 1 for translations of that version
            # - 1 for applications versions of that version
            # - 1 for authors
            # - 1 for previews
            # - 1 for license
            # - 1 for translations of the license
            # - 1 for webext permissions
            # - 1 for promoted addon
            # - 1 for tags
            self._test_url(lang='en-US')

        with self.assertNumQueries(16):
            # One additional query for region exclusions test
            self._test_url(lang='en-US', extra={'HTTP_X_COUNTRY_CODE': 'fr'})

    @mock.patch('django_statsd.middleware.statsd.timing')
    def test_statsd_timings(self, statsd_timing_mock):
        self._test_url()
        assert statsd_timing_mock.call_count == 4
        assert (
            statsd_timing_mock.call_args_list[0][0][0]
            == 'timer.olympia.addons.models.transformer'
        )
        assert (
            statsd_timing_mock.call_args_list[1][0][0]
            == 'view.olympia.addons.views.AddonViewSet.GET'
        )
        assert (
            statsd_timing_mock.call_args_list[2][0][0]
            == 'view.olympia.addons.views.GET'
        )
        assert statsd_timing_mock.call_args_list[3][0][0] == 'view.GET'

    def test_detail_url_with_reviewers_in_the_url(self):
        self.addon.update(slug='something-reviewers')
        self.url = reverse_ns('addon-detail', kwargs={'pk': self.addon.slug})
        self._test_url()

    def test_hide_latest_unlisted_version_anonymous(self):
        unlisted_version = version_factory(
            addon=self.addon, channel=amo.CHANNEL_UNLISTED
        )
        unlisted_version.update(created=self.days_ago(1))
        result = self._test_url()
        assert 'latest_unlisted_version' not in result

    def test_hide_latest_unlisted_version_simple_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        unlisted_version = version_factory(
            addon=self.addon, channel=amo.CHANNEL_UNLISTED
        )
        unlisted_version.update(created=self.days_ago(1))
        result = self._test_url()
        assert 'latest_unlisted_version' not in result

    def test_show_latest_unlisted_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)

        unlisted_version = version_factory(
            addon=self.addon, channel=amo.CHANNEL_UNLISTED
        )
        unlisted_version.update(created=self.days_ago(1))
        result = self._test_url()
        assert result['latest_unlisted_version']
        assert result['latest_unlisted_version']['id'] == unlisted_version.pk

    def test_show_latest_unlisted_version_unlisted_reviewer(self):
        user = UserProfile.objects.create(username='author')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.client.login_api(user)

        unlisted_version = version_factory(
            addon=self.addon, channel=amo.CHANNEL_UNLISTED
        )
        unlisted_version.update(created=self.days_ago(1))
        result = self._test_url()
        assert result['latest_unlisted_version']
        assert result['latest_unlisted_version']['id'] == unlisted_version.pk

    def test_show_latest_unlisted_version_unlisted_viewer(self):
        user = UserProfile.objects.create(username='author')
        self.grant_permission(user, 'ReviewerTools:ViewUnlisted')
        self.client.login_api(user)

        unlisted_version = version_factory(
            addon=self.addon, channel=amo.CHANNEL_UNLISTED
        )
        unlisted_version.update(created=self.days_ago(1))
        result = self._test_url()
        assert result['latest_unlisted_version']
        assert result['latest_unlisted_version']['id'] == unlisted_version.pk

    def test_with_lang(self):
        self.addon.name = {
            'en-US': 'My Addôn, mine',
            'fr': 'Mon Addôn, le mien',
        }
        self.addon.save()

        response = self.client.get(self.url, {'lang': 'en-US'})
        assert response.status_code == 200
        result = json.loads(force_str(response.content))
        assert result['id'] == self.addon.pk
        assert result['name'] == {'en-US': 'My Addôn, mine'}

        response = self.client.get(self.url, {'lang': 'fr'})
        assert response.status_code == 200
        result = json.loads(force_str(response.content))
        assert result['id'] == self.addon.pk
        assert result['name'] == {'fr': 'Mon Addôn, le mien'}

        response = self.client.get(self.url, {'lang': 'de'})
        assert response.status_code == 200
        result = json.loads(force_str(response.content))
        assert result['id'] == self.addon.pk
        assert result['name'] == {
            'en-US': 'My Addôn, mine',
            'de': None,
            '_default': 'en-US',
        }
        assert list(result['name'])[0] == 'en-US'

        overridden_api_gates = {'v5': ('l10n_flat_input_output',)}
        with override_settings(DRF_API_GATES=overridden_api_gates):
            response = self.client.get(self.url, {'lang': 'en-US'})
            assert response.status_code == 200
            result = json.loads(force_str(response.content))
            assert result['id'] == self.addon.pk
            assert result['name'] == 'My Addôn, mine'

            response = self.client.get(self.url, {'lang': 'fr'})
            assert response.status_code == 200
            result = json.loads(force_str(response.content))
            assert result['id'] == self.addon.pk
            assert result['name'] == 'Mon Addôn, le mien'

            response = self.client.get(self.url, {'lang': 'de'})
            assert response.status_code == 200
            result = json.loads(force_str(response.content))
            assert result['id'] == self.addon.pk
            assert result['name'] == 'My Addôn, mine'

    def test_with_wrong_app_and_appversion_params(self):
        # These parameters should only work with langpacks, and are ignored
        # for the rest. Although the code lives in the serializer, this is
        # tested on the view to make sure the error is propagated back
        # correctly up to the view, generating a 400 error and not a 500.
        # appversion without app
        self.addon.update(type=amo.ADDON_LPAPP)

        # Missing app
        response = self.client.get(self.url, {'appversion': '58.0'})
        assert response.status_code == 400
        data = json.loads(force_str(response.content))
        assert data == {'detail': 'Invalid "app" parameter.'}

        # Invalid appversion
        response = self.client.get(self.url, {'appversion': 'fr', 'app': 'firefox'})
        assert response.status_code == 400
        data = json.loads(force_str(response.content))
        assert data == {'detail': 'Invalid "appversion" parameter.'}

        # Invalid app
        response = self.client.get(self.url, {'appversion': '58.0', 'app': 'fr'})
        assert response.status_code == 400
        data = json.loads(force_str(response.content))
        assert data == {'detail': 'Invalid "app" parameter.'}

    def test_with_grouped_ratings(self):
        assert 'grouped_counts' not in self.client.get(self.url).json()['ratings']

        response = self.client.get(self.url, {'show_grouped_ratings': 'true'})
        assert 'grouped_counts' in response.json()['ratings']
        assert response.json()['ratings']['grouped_counts'] == {
            '1': 0,
            '2': 0,
            '3': 0,
            '4': 0,
            '5': 0,
        }

        response = self.client.get(self.url, {'show_grouped_ratings': '58.0'})
        assert response.status_code == 400
        data = json.loads(force_str(response.content))
        assert data == {'detail': 'show_grouped_ratings parameter should be a boolean'}


class RequestMixin:
    client_request_verb = None

    def request(self, *, data=None, format=None, user_agent='web-ext/12.34', **kwargs):
        verb = getattr(self.client, self.client_request_verb, None)
        if not verb:
            raise NotImplementedError
        return verb(
            self.url,
            data={**getattr(self, 'minimal_data', {}), **(data or kwargs)},
            format=format,
            HTTP_USER_AGENT=user_agent,
        )


class AddonViewSetCreateUpdateMixin(RequestMixin):
    SUCCESS_STATUS_CODE = 200

    def test_set_contributions_url(self):
        response = self.request(contributions_url='https://foo.baa/xxx')
        assert response.status_code == 400, response.content
        domains = ', '.join(amo.VALID_CONTRIBUTION_DOMAINS)
        assert response.data == {
            'contributions_url': [f'URL domain must be one of [{domains}].']
        }

        response = self.request(contributions_url='http://sub.flattr.com/xxx')
        assert response.status_code == 400, response.content
        assert response.data == {
            'contributions_url': [
                f'URL domain must be one of [{domains}].',
                'URLs must start with https://.',
            ]
        }

        valid_url = 'https://flattr.com/xxx'
        response = self.request(contributions_url=valid_url)
        assert response.status_code == self.SUCCESS_STATUS_CODE, response.content
        assert response.data['contributions_url']['url'].startswith(valid_url)
        addon = Addon.objects.get()
        assert addon.contributions == valid_url

    def test_set_contributions_url_github(self):
        response = self.request(contributions_url='https://github.com/xxx')
        assert response.status_code == 400, response.content
        assert response.data == {
            'contributions_url': [
                'URL path for GitHub Sponsors must contain /sponsors/.',
            ]
        }

        valid_url = 'https://github.com/sponsors/xxx'
        response = self.request(contributions_url=valid_url)
        assert response.status_code == self.SUCCESS_STATUS_CODE, response.content
        assert response.data['contributions_url']['url'].startswith(valid_url)
        addon = Addon.objects.get()
        assert addon.contributions == valid_url

    def test_contributions_url_too_long(self):
        url = f'https://flattr.com/{"x" * 237}'
        response = self.request(contributions_url=url)
        assert response.status_code == 400
        assert response.data == {
            'contributions_url': [
                ErrorDetail(
                    string='Ensure this field has no more than 255 characters.',
                    code='max_length',
                )
            ]
        }

    def test_name_trademark(self):
        name = {'en-US': 'FIREFOX foo', 'fr': 'lé Mozilla baa'}
        response = self.request(name=name)
        assert response.status_code == 400, response.content
        assert response.data == {
            'name': ['Add-on names cannot contain the Mozilla or Firefox trademarks.']
        }

        self.grant_permission(self.user, 'Trademark:Bypass')
        response = self.request(name=name)
        assert response.status_code == self.SUCCESS_STATUS_CODE, response.content
        assert response.data['name'] == name
        addon = Addon.objects.get()
        assert addon.name == name['en-US']

    def test_name_for_trademark(self):
        # But the form "x for Firefox" is allowed
        allowed_name = {'en-US': 'name for FIREFOX', 'fr': 'nom for Mozilla'}
        response = self.request(name=allowed_name)
        assert response.status_code == self.SUCCESS_STATUS_CODE, response.content
        assert response.data['name'] == allowed_name
        addon = Addon.objects.get()
        assert addon.name == allowed_name['en-US']

    def test_name_and_summary_not_symbols_only(self):
        response = self.request(name={'en-US': '()+([#'}, summary={'en-US': '±↡∋⌚'})
        assert response.status_code == 400, response.content
        assert response.data == {
            'name': [
                'Ensure this field contains at least one letter or number character.'
            ],
            'summary': [
                'Ensure this field contains at least one letter or number character.'
            ],
        }

        # 'ø' and 'ɵ' are not symbols, they are letters, so it should be valid.
        response = self.request(name={'en-US': 'ø'}, summary={'en-US': 'ɵ'})
        assert response.status_code == self.SUCCESS_STATUS_CODE, response.content
        assert response.data['name'] == {'en-US': 'ø'}
        assert response.data['summary'] == {'en-US': 'ɵ'}
        addon = Addon.objects.get()
        assert addon.name == 'ø'
        assert addon.summary == 'ɵ'


class TestAddonViewSetCreate(UploadMixin, AddonViewSetCreateUpdateMixin, TestCase):
    client_class = APITestClientSessionID
    client_request_verb = 'post'
    SUCCESS_STATUS_CODE = 201
    APPVERSION_HIGHER_THAN_EVERYTHING_ELSE = '121.0'

    @classmethod
    def setUpTestData(cls):
        versions = {
            amo.DEFAULT_WEBEXT_MIN_VERSION,
            amo.DEFAULT_WEBEXT_MIN_VERSION_NO_ID,
            amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID,
            amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX,
            amo.DEFAULT_WEBEXT_DICT_MIN_VERSION_FIREFOX,
            amo.DEFAULT_WEBEXT_MAX_VERSION,
            amo.DEFAULT_WEBEXT_MIN_VERSION_MV3_FIREFOX,
            amo.DEFAULT_WEBEXT_MIN_VERSION_GECKO_ANDROID,
            amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY,
            cls.APPVERSION_HIGHER_THAN_EVERYTHING_ELSE,
        }
        for version in versions:
            AppVersion.objects.get_or_create(
                application=amo.FIREFOX.id, version=version
            )
            AppVersion.objects.get_or_create(
                application=amo.ANDROID.id, version=version
            )

    def setUp(self):
        super().setUp()
        self.user = user_factory(read_dev_agreement=self.days_ago(0))
        self.upload = self.get_upload(
            'webextension.xpi',
            user=self.user,
            source=amo.UPLOAD_SOURCE_ADDON_API,
            channel=amo.CHANNEL_UNLISTED,
        )
        self.url = reverse_ns('addon-list', api_version='v5')
        self.client.login_api(self.user)
        self.license = License.objects.create(builtin=1)
        self.minimal_data = {'version': {'upload': self.upload.uuid}}
        self.statsd_incr_mock = self.patch('olympia.addons.serializers.statsd.incr')

    def test_basic_unlisted(self):
        response = self.request()
        assert response.status_code == 201, response.content
        data = response.data
        assert data['name'] == {'en-US': 'My WebExtension Addon'}
        assert data['status'] == 'incomplete'
        addon = Addon.objects.get()
        request = APIRequestFactory().get('/')
        request.version = 'v5'
        request.user = self.user
        expected_version = addon.find_latest_version(channel=None)
        assert expected_version.channel == amo.CHANNEL_UNLISTED
        expected_data = DeveloperAddonSerializer(
            context={'request': request}
        ).to_representation(addon)
        # The additional `version` property contains the version we just
        # uploaded.
        expected_data['version'] = DeveloperVersionSerializer(
            context={'request': request}
        ).to_representation(expected_version)
        assert dict(data) == dict(expected_data)
        assert (
            ActivityLog.objects.for_addons(addon)
            .filter(action=amo.LOG.CREATE_ADDON.id)
            .count()
            == 1
        )
        self.statsd_incr_mock.assert_any_call('addons.submission.addon.unlisted')
        self.statsd_incr_mock.assert_any_call('addons.submission.webext_version.12_34')
        provenance = VersionProvenance.objects.get()
        assert provenance.version == expected_version
        assert provenance.source == amo.UPLOAD_SOURCE_ADDON_API
        assert provenance.client_info == 'web-ext/12.34'

    def test_invalid_upload(self):
        self.upload.update(valid=False)
        response = self.request()
        assert response.status_code == 400
        assert response.json() == {'version': {'upload': ['Upload is not valid.']}}

    def test_not_own_upload(self):
        self.upload.update(user=user_factory())
        response = self.request()
        assert response.status_code == 400
        assert response.json() == {'version': {'upload': ['Upload is not valid.']}}

    def test_duplicate_addon_id(self):
        response = self.request()
        assert response.status_code == 201, response.content
        self.upload = self.get_upload(
            'webextension.xpi',
            user=self.user,
            source=amo.UPLOAD_SOURCE_ADDON_API,
            channel=amo.CHANNEL_UNLISTED,
        )
        self.minimal_data = {'version': {'upload': self.upload.uuid}}
        response = self.request()
        assert response.status_code == 409, response.status_code
        assert response.json() == {'version': ['Duplicate add-on ID found.']}

    def test_basic_listed(self):
        self.upload.update(channel=amo.CHANNEL_LISTED)
        response = self.request(
            data={
                'categories': ['bookmarks'],
                'version': {
                    'upload': self.upload.uuid,
                    'license': self.license.slug,
                },
            },
        )
        assert response.status_code == 201, response.content
        data = response.data
        assert data['name'] == {'en-US': 'My WebExtension Addon'}
        assert data['status'] == 'nominated'
        addon = Addon.objects.get()
        request = APIRequestFactory().get('/')
        request.version = 'v5'
        request.user = self.user
        expected_version = addon.find_latest_version(channel=None)
        assert expected_version.channel == amo.CHANNEL_LISTED
        expected_data = DeveloperAddonSerializer(
            context={'request': request}
        ).to_representation(addon)
        expected_data = OrderedDict(sorted(expected_data.items()))
        # The additional `version` property contains the version we just
        # uploaded.
        expected_data['version'] = DeveloperVersionSerializer(
            context={'request': request}
        ).to_representation(expected_version)
        assert dict(data) == dict(expected_data)
        assert (
            ActivityLog.objects.for_addons(addon)
            .filter(action=amo.LOG.CREATE_ADDON.id)
            .count()
            == 1
        )
        self.statsd_incr_mock.assert_any_call('addons.submission.addon.listed')
        self.statsd_incr_mock.assert_any_call('addons.submission.webext_version.12_34')
        provenance = VersionProvenance.objects.get()
        assert provenance.version == expected_version
        assert provenance.source == amo.UPLOAD_SOURCE_ADDON_API
        assert provenance.client_info == 'web-ext/12.34'

    def test_no_client_info(self):
        self.upload.update(channel=amo.CHANNEL_LISTED)
        response = self.request(
            data={
                'categories': ['bookmarks'],
                'version': {
                    'upload': self.upload.uuid,
                    'license': self.license.slug,
                },
            },
            user_agent='',
        )
        assert response.status_code == 201, response.content
        addon = Addon.objects.get()
        expected_version = addon.find_latest_version(channel=None)
        provenance = VersionProvenance.objects.get()
        assert provenance.version == expected_version
        assert provenance.source == amo.UPLOAD_SOURCE_ADDON_API
        assert provenance.client_info == ''

    def test_listed_metadata_missing(self):
        self.upload.update(channel=amo.CHANNEL_LISTED)
        response = self.request(
            data={
                'version': {'upload': self.upload.uuid},
            },
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'version': {
                'license': [
                    'This field, or custom_license, is required for listed versions.'
                ]
            },
        }

        # If the license is set we'll get further validation errors from addon
        # Mocking parse_addon so we can test the fallback to POST data when there are
        # missing manifest fields.
        with mock.patch('olympia.addons.serializers.parse_addon') as parse_addon_mock:
            parse_addon_mock.side_effect = lambda *arg, **kw: {
                key: value
                for key, value in parse_addon(*arg, **kw).items()
                if key not in ('name', 'summary')
            }
            response = self.request(
                data={
                    'summary': {'en-US': 'replacement summary'},
                    'name': {},  # will override the name in the manifest
                    'version': {
                        'upload': self.upload.uuid,
                        'license': self.license.slug,
                    },
                },
            )
        assert response.status_code == 400, response.content
        assert response.data == {
            'categories': ['This field is required for add-ons with listed versions.'],
            'name': ['This field is required for add-ons with listed versions.'],
            # 'summary': summary was provided via POST, so we're good
        }

    def test_listed_metadata_null(self):
        self.upload.update(channel=amo.CHANNEL_LISTED)
        # name and summary are defined in the manifest but we're trying override them
        response = self.request(
            data={
                'summary': {'en-US': None},
                'name': {'en-US': None},
                'categories': ['bookmarks'],
                'version': {
                    'upload': self.upload.uuid,
                    'license': self.license.slug,
                },
            },
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'name': ['This field may not be null.'],
            'summary': ['This field may not be null.'],
        }

    def test_not_authenticated(self):
        self.client.logout_api()
        response = self.request()
        assert response.status_code == 401
        assert response.data == {
            'detail': 'Authentication credentials were not provided.'
        }
        assert not Addon.objects.all()

    def test_not_read_agreement(self):
        self.user.update(read_dev_agreement=None)
        response = self.request()
        assert response.status_code in [401, 403]  # JWT auth is a 401; web auth is 403
        assert 'agreement' in response.data['detail'].lower()
        assert not Addon.objects.all()

    def test_waffle_flag_disabled(self):
        gates = {
            'v5': (
                gate
                for gate in settings.DRF_API_GATES['v5']
                if gate != 'addon-submission-api'
            )
        }
        with override_settings(DRF_API_GATES=gates):
            response = self.request()
        assert response.status_code == 403
        assert response.data == {
            'detail': 'You do not have permission to perform this action.'
        }
        assert not Addon.objects.all()

    def test_missing_version(self):
        self.minimal_data = {}
        response = self.request(data={'categories': ['bookmarks']})
        assert response.status_code == 400, response.content
        assert response.data == {'version': ['This field is required.']}
        assert not Addon.objects.all()

    def test_invalid_categories(self):
        response = self.request(
            # performance is an android category
            data={'categories': ['performance']},
        )
        assert response.status_code == 400, response.content
        assert response.data == {'categories': ['Invalid category name.']}

        response = self.request(
            # general is an firefox category but for dicts and lang packs
            data={'categories': ['general']}
        )
        assert response.status_code == 400, response.content
        assert response.data == {'categories': ['Invalid category name.']}
        assert not Addon.objects.all()

    def test_other_category_cannot_be_combined(self):
        response = self.request(data={'categories': ['bookmarks', 'other']})
        assert response.status_code == 400, response.content
        assert response.data == {
            'categories': [
                'The "other" category cannot be combined with another category'
            ]
        }
        assert not Addon.objects.all()

    def test_too_many_categories(self):
        response = self.request(
            data={
                'categories': [
                    'appearance',
                    'download-management',
                    'shopping',
                    'games-entertainment',
                ]
            },
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'categories': ['Maximum number of categories per application (3) exceeded']
        }
        assert not Addon.objects.all()

    def test_set_slug(self):
        # Check for slugs with invalid characters in it
        response = self.request(data={'slug': '!@!#!@##@$$%$#%#%$^^%&%'})
        assert response.status_code == 400, response.content
        assert response.data == {
            'slug': [
                'Enter a valid “slug” consisting of letters, numbers, underscores or '
                'hyphens.'
            ]
        }

        # Check for a slug in the DeniedSlug list
        DeniedSlug.objects.create(name='denied-slug')
        response = self.request(data={'slug': 'denied-slug'})
        assert response.status_code == 400, response.content
        assert response.data == {
            'slug': ['This slug cannot be used. Please choose another.']
        }

        # Check for all numeric slugs - DeniedSlug.blocked checks for these too.
        response = self.request(data={'slug': '1234'})
        assert response.status_code == 400, response.content
        assert response.data == {
            'slug': ['This slug cannot be used. Please choose another.']
        }

    def test_slug_uniqueness(self):
        # Check for duplicate - we get this for free because Addon.slug is unique=True
        addon_factory(slug='foo', status=amo.STATUS_DISABLED)
        response = self.request(
            data={
                'slug': 'foo',
            },
        )
        assert response.status_code == 400, response.content
        assert response.data == {'slug': ['addon with this slug already exists.']}

    def test_set_extra_data(self):
        self.upload.update(channel=amo.CHANNEL_LISTED)
        data = {
            'categories': ['bookmarks'],
            'description': {'en-US': 'new description'},
            'developer_comments': {'en-US': 'comments'},
            'homepage': {'en-US': 'https://my.home.page/'},
            'is_experimental': True,
            'requires_payment': True,
            # 'name'  # don't update - should retain name from the manifest
            'slug': 'addon-Slug',
            'summary': {'en-US': 'new summary', 'fr': 'lé summary'},
            'support_email': {'en-US': 'email@me.me'},
            'support_url': {'en-US': 'https://my.home.page/support/'},
            'version': {
                'upload': self.upload.uuid,
                'license': self.license.slug,
                'approval_notes': 'approve me!',
            },
        }
        response = self.request(**data)

        assert response.status_code == 201, response.content
        addon = Addon.objects.get()
        data = response.data
        assert data['categories'] == ['bookmarks']  # v5 representation
        assert addon.all_categories == [CATEGORIES[amo.ADDON_EXTENSION]['bookmarks']]
        response = {'lol': 'blah'}
        assert data['description'] == {'en-US': 'new description'}
        assert addon.description == 'new description'
        assert data['developer_comments'] == {'en-US': 'comments'}
        assert addon.developer_comments == 'comments'
        assert data['homepage']['url'] == {'en-US': 'https://my.home.page/'}
        assert addon.homepage == 'https://my.home.page/'
        assert data['is_experimental'] is True
        assert addon.is_experimental is True
        assert data['requires_payment'] is True
        assert addon.requires_payment is True
        assert data['name'] == {'en-US': 'My WebExtension Addon'}
        assert addon.name == 'My WebExtension Addon'
        # addon.slug always gets slugified back to lowercase
        assert data['slug'] == 'addon-slug' == addon.slug
        assert data['summary'] == {'en-US': 'new summary', 'fr': 'lé summary'}
        assert addon.summary == 'new summary'
        with self.activate(locale='fr'):
            assert Addon.objects.get().summary == 'lé summary'
        assert data['support_email'] == {'en-US': 'email@me.me'}
        assert addon.support_email == 'email@me.me'
        assert data['support_url']['url'] == {'en-US': 'https://my.home.page/support/'}
        assert addon.support_url == 'https://my.home.page/support/'
        assert (
            data['current_version']['approval_notes']
            == addon.current_version.approval_notes
            == 'approve me!'
        )
        self.statsd_incr_mock.assert_any_call('addons.submission.addon.listed')

    def test_override_manifest_localization(self):
        upload = self.get_upload(
            'notify-link-clicks-i18n.xpi',
            user=self.user,
            source=amo.UPLOAD_SOURCE_ADDON_API,
            channel=amo.CHANNEL_UNLISTED,
        )
        data = {
            # 'name'  # don't update - should retain name from the manifest
            'summary': {'en-US': 'new summary', 'fr': 'lé summary'},
            'version': {'upload': upload.uuid, 'license': self.license.slug},
        }
        response = self.request(**data)

        assert response.status_code == 201, response.content
        addon = Addon.objects.get()
        data = response.data
        assert data['name'] == {
            'de': 'Meine Beispielerweiterung',
            'en-US': 'Notify link clicks i18n',
            'ja': 'リンクを通知する',
            'nb-NO': 'Varsling ved trykk på lenke i18n',
            'nl': 'Meld klikken op hyperlinks',
            'sv-SE': 'Meld klikken op hyperlinks',
        }
        assert addon.name == 'Notify link clicks i18n'
        assert data['summary'] == {
            'en-US': 'new summary',
            'fr': 'lé summary',
        }
        assert addon.summary == 'new summary'
        with self.activate(locale='fr'):
            assert Addon.objects.get().summary == 'lé summary'

    def test_fields_max_length(self):
        data = {
            'name': {'fr': 'é' * 51, 'en-US': 'some english name'},
            'summary': {'en-US': 'a' * 251},
        }
        response = self.request(**data)
        assert response.status_code == 400, response.content
        assert response.data == {
            'name': ['Ensure this field has no more than 50 characters.'],
            'summary': ['Ensure this field has no more than 250 characters.'],
        }

    def test_empty_strings_disallowed(self):
        # if a string is required-ish (at least in some circumstances) we'll prevent
        # empty strings
        data = {
            'summary': {'en-US': ''},
            'name': {'en-US': ''},
        }
        response = self.request(**data)
        assert response.status_code == 400, response.content
        assert response.data == {
            'summary': ['This field may not be blank.'],
            'name': ['This field may not be blank.'],
        }

    def test_set_disabled(self):
        response = self.request(
            data={
                'is_disabled': True,
            }
        )
        addon = Addon.objects.get()

        assert response.status_code == 201, response.content
        assert response.data['is_disabled'] is True
        assert addon.is_disabled is True
        assert addon.disabled_by_user is True  # sets the user property

    @override_settings(EXTERNAL_SITE_URL='https://amazing.site')
    def test_set_homepage_support_url_email(self):
        data = {
            'homepage': {'en-US': '#%^%&&%^&^&^*'},
            'support_email': {'en-US': '#%^%&&%^&^&^*'},
            'support_url': {'en-US': '#%^%&&%^&^&^*'},
        }
        response = self.request(**data)

        assert response.status_code == 400, response.content
        assert response.data == {
            'homepage': ['Enter a valid URL.'],
            'support_email': ['Enter a valid email address.'],
            'support_url': ['Enter a valid URL.'],
        }

        data = {
            'homepage': {'en-US': f'{settings.EXTERNAL_SITE_URL}'},
            'support_url': {'en-US': f'{settings.EXTERNAL_SITE_URL}/foo/'},
        }
        response = self.request(**data)
        msg = (
            'This field can only be used to link to external websites. '
            f'URLs on {settings.EXTERNAL_SITE_URL} are not allowed.'
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'homepage': [msg],
            'support_url': [msg],
        }

        data = {
            'homepage': {'en-US': 'ftp://somewhere.com/foo'},
            'support_url': {'en-US': 'ftp://somewhere.com'},
        }
        response = self.request(
            data=data,
        )
        msg = 'Enter a valid URL.'
        assert response.status_code == 400, response.content
        assert response.data == {
            'homepage': [msg],
            'support_url': [msg],
        }

    def test_set_data_too_long(self):
        data = {
            'homepage': {'fr': f'https://example.com/{"a" * 236}'},
            'support_url': {'fr': f'https://example.com/{"b" * 236}'},
            'support_email': {'fr': f'{"c" * 90}@abcdef.com'},
        }
        response = self.request(**data)
        assert response.status_code == 400, response.content
        assert response.data == {
            'homepage': [
                ErrorDetail(
                    string='Ensure this field has no more than 255 characters.',
                    code='max_length',
                ),
            ],
            'support_url': [
                ErrorDetail(
                    string='Ensure this field has no more than 255 characters.',
                    code='max_length',
                ),
            ],
            'support_email': [
                ErrorDetail(
                    string='Ensure this field has no more than 100 characters.',
                    code='max_length',
                ),
            ],
        }

    def test_set_data_too_long_other_textfields(self):
        data = {
            'description': {'fr': 'é' * 15001},
            'developer_comments': {'fr': 'ö' * 3001},
        }
        response = self.request(**data)
        assert response.status_code == 400, response.content
        assert response.data == {
            'description': [
                ErrorDetail(
                    string='Ensure this field has no more than 15000 characters.',
                    code='max_length',
                ),
            ],
            'developer_comments': [
                ErrorDetail(
                    string='Ensure this field has no more than 3000 characters.',
                    code='max_length',
                ),
            ],
        }

    def test_set_tags(self):
        response = self.request(data={'tags': ['foo', 'bar']})
        assert response.status_code == 400, response.content
        assert response.data == {
            'tags': {
                0: ['"foo" is not a valid choice.'],
                1: ['"bar" is not a valid choice.'],
            }
        }

        response = self.request(
            data={
                'tags': list(Tag.objects.values_list('tag_text', flat=True)),
            },
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'tags': ['Ensure this field has no more than 10 elements.'],
        }

        response = self.request(
            data={'tags': ['zoom', 'music']},
        )
        assert response.status_code == 201, response.content
        assert response.data['tags'] == ['zoom', 'music']
        addon = Addon.objects.get()
        assert [tag.tag_text for tag in addon.tags.all()] == ['music', 'zoom']

    def test_default_locale_with_invalid_locale(self):
        response = self.request(data={'default_locale': 'zz'})
        assert response.status_code == 400
        assert response.data == {'default_locale': ['"zz" is not a valid choice.']}

    def test_default_locale(self):
        # An xpi without localization - the values are in the manifest directly so will
        # be intepretted as whatever locale is specified as the default locale.
        response = self.request(
            data={
                'default_locale': 'fr',
                # the field will have a translation in de, but won't have a value in fr
                'description': {'de': 'Das description'},
            },
        )
        assert response.status_code == 400, response.data
        error_string = 'A value in the default locale of "fr" is required.'
        assert response.data == {
            'description': [error_string],
        }

        # success cases, all tested with the post request with the different fields
        # A field is provided with a value in new default
        # B field already has a value in new default
        # C field has no other translations
        response = self.request(
            data={
                'default_locale': 'fr',
                'name': {'fr': 'nom française'},  # A - a value in fr
                # B no summary provided, but has a value in the manifest already
                # C no description and doesn't have other translations
            },
        )
        assert response.status_code == 201, response.data
        addon = Addon.objects.get()
        assert addon.default_locale == 'fr'
        # from the postdata
        assert addon.name == 'nom française'
        assert addon.name.locale == 'fr'
        # summary value is from the manifest
        assert addon.summary == 'just a test addon with the manifest.json format'
        assert addon.summary.locale == 'fr'
        # and there is no description either in the manifest or provided in post
        assert addon.description is None

    def test_localized_xpi_default_locale_override(self):
        # This xpi has localized values in the xpi, but has been crafted to not have a
        # name translation for de, which is valid if the default_locale is another lang,
        # but won't be valid if the default_locale is de.
        upload = self.get_upload(
            'notify-link-clicks-i18n-missing.xpi',
            user=self.user,
            source=amo.UPLOAD_SOURCE_ADDON_API,
            channel=amo.CHANNEL_UNLISTED,
        )

        # failure cases:
        # A field doesn't have a value in the xpi in new default, or
        # B field has other translations provided
        response = self.request(
            data={
                'version': {'upload': upload.uuid},
                'default_locale': 'de',
                # A no name provided for de, and our xpi is missing name in de
                'support_url': {'it': 'https://it.support.test/'},  # B
            },
        )
        assert response.status_code == 400, response.data
        error_string = 'A value in the default locale of "de" is required.'
        assert response.data == {
            'name': [error_string],
            'support_url': [error_string],
        }

        # success cases, all tested with the post request with the different fields:
        # A field is provided with a value in new default
        # B field already has a value in new default
        # C field isn't required and has no other translations
        response = self.request(
            data={
                'version': {'upload': upload.uuid},
                'default_locale': 'de',
                'name': {'de': 'Das Name'},  # A
                # B no summary provided, but the xpi already has a translation in de
                # C no support_url provided and there aren't other translations
            },
        )
        assert response.status_code == 201, response.data
        with self.activate('fr'):  # a locale the xpi doesn't have so we get defaults
            addon = Addon.objects.get()
        assert addon.default_locale == 'de'
        # from the postdata
        assert addon.name == 'Das Name'
        assert addon.name.locale == 'de'
        # summary is from the xpi translation json files
        assert addon.summary == 'Benachrichtigt den Benutzer über Linkklicks'
        assert addon.summary.locale == 'de'
        # and there is no description either in the xpi, manifest or provided in post
        assert addon.description is None
        # homepage is defined directly in the manifest, and is not localized, so just
        # testing the mix of translated and not translated is working as expected
        assert str(addon.homepage).startswith('https://github.com/mdn/')
        assert addon.homepage.locale == 'de'

    def test_localized_xpi(self):
        upload = self.get_upload(
            'notify-link-clicks-i18n-missing.xpi',
            user=self.user,
            source=amo.UPLOAD_SOURCE_ADDON_API,
            channel=amo.CHANNEL_LISTED,
        )

        # the default_locale isn't overriden from the xpi - it's en-US
        response = self.request(
            data={
                'version': {'upload': upload.uuid, 'license': self.license.slug},
                'categories': ['other'],
                'support_email': {  # this field has the required locales
                    'it': 'rusiczki.ioana@gmail.com',
                    'ro': 'rusiczki.ioana@gmail.com',
                    'en-US': 'rusiczki.ioana@gmail.com',
                },
                # The following fields are missing en-US localizations
                'name': {'it': 'test'},
                'developer_comments': {'it': 'test'},
                'summary': {'it': 'summaria italiano'},
            },
        )
        assert response.status_code == 400, response.data
        error_string = 'A value in the default locale of "en-US" is required.'
        assert response.data == {
            'name': [error_string],
            'developer_comments': [error_string],
            'summary': [error_string],
        }

        # compared to previous request:
        #  - omitted developer comments as not a required field
        #  - changed name to be en-US only
        #  - added a summary value in en-US in addition to it
        response = self.request(
            data={
                'version': {'upload': upload.uuid, 'license': self.license.slug},
                'categories': ['other'],
                'support_email': {
                    'it': 'rusiczki.ioana@gmail.com',
                    'ro': 'rusiczki.ioana@gmail.com',
                    'en-US': 'rusiczki.ioana@gmail.com',
                },
                'name': {'en-US': 'name'},
                'summary': {'en-US': 'summary', 'it': 'summaria italiano'},
            },
        )
        assert response.status_code == 201, response.data
        assert response.data['name'] == {'en-US': 'name'}
        assert response.data['summary'] == {
            'en-US': 'summary',
            'it': 'summaria italiano',
        }

    def test_langpack(self):
        AppVersion.objects.create(application=amo.FIREFOX.id, version='66.0a1')
        upload = self.get_upload(
            'webextension_langpack.xpi',
            user=self.user,
            source=amo.UPLOAD_SOURCE_ADDON_API,
            channel=amo.CHANNEL_UNLISTED,
        )
        self.minimal_data = {'version': {'upload': upload.uuid}}
        self.grant_permission(self.user, ':'.join(amo.permissions.LANGPACK_SUBMIT))

        response = self.request()
        assert response.status_code == 201, response.content
        data = response.data
        assert data['name'] == {'en-US': 'My Language Pack'}
        addon = Addon.objects.get()
        assert addon.type == amo.ADDON_LPAPP
        assert addon.target_locale == 'de'
        version = addon.find_latest_version(channel=None)
        assert version.file.strict_compatibility is True
        assert version.apps.get().application == amo.FIREFOX.id

    def test_compatibility_langpack(self):
        AppVersion.objects.create(application=amo.FIREFOX.id, version='66.0a1')
        upload = self.get_upload(
            'webextension_langpack.xpi',
            user=self.user,
            source=amo.UPLOAD_SOURCE_ADDON_API,
            channel=amo.CHANNEL_UNLISTED,
        )
        self.minimal_data = {'version': {'upload': upload.uuid}}
        self.grant_permission(self.user, ':'.join(amo.permissions.LANGPACK_SUBMIT))

        response = self.request(
            data={
                'version': {
                    **self.minimal_data['version'],
                    'compatibility': ['android'],
                }
            }
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'version': {
                'compatibility': [
                    'Language Packs are not supported by Firefox for Android'
                ]
            }
        }

    def test_dictionary_compat(self):
        def _parse_xpi_mock(pkg, *, addon, minimal, user, **kwargs):
            return {
                **parse_xpi(pkg, addon=addon, minimal=minimal, user=user),
                'type': amo.ADDON_DICT,
            }

        with patch('olympia.files.utils.parse_xpi', side_effect=_parse_xpi_mock):
            response = self.request(
                data={
                    'version': {
                        **self.minimal_data['version'],
                        'compatibility': ['android'],
                    }
                }
            )
            assert response.status_code == 400, response.content
            assert response.data == {
                'version': {
                    'compatibility': [
                        'This type of add-on does not allow custom compatibility.'
                    ]
                }
            }

            response = self.request()
            assert response.status_code == 201, response.content
            assert response.data['type'] == 'dictionary'

    def test_compatibility_dict(self):
        request_data = {'version': {'upload': self.upload.uuid, 'compatibility': {}}}
        response = self.request(data=request_data)
        assert response.status_code == 400, response.content
        assert response.data == {'version': {'compatibility': ['Invalid value']}}

        request_data['version']['compatibility'] = {
            'firefox': {'min': '61.0'},
            'foo': {},
        }
        response = self.request(data=request_data)
        assert response.status_code == 400, response.content
        assert response.data == {
            'version': {'compatibility': ['Invalid app specified']}
        }

        # 61.0 (DEFAULT_WEBEXT_DICT_MIN_VERSION_FIREFOX) should be valid.
        request_data['version']['compatibility'] = {
            'firefox': {'min': '61.0'},
            'android': {},
        }
        response = self.request(data=request_data)
        assert response.status_code == self.SUCCESS_STATUS_CODE, response.content
        data = response.data

        addon = Addon.objects.get()
        assert addon.versions.count() == 1
        version = addon.find_latest_version(channel=None)
        assert data['version']['compatibility'] == {
            # android was specified but with an empty dict, so gets the default
            # corrected to account for general availability.
            'android': {'max': '*', 'min': amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY},
            # firefox max wasn't specified, so is the default max app version
            'firefox': {'max': '*', 'min': '61.0'},
        }
        assert list(version.compatible_apps.keys()) == [amo.FIREFOX, amo.ANDROID]
        for avs in version.compatible_apps.values():
            assert avs.originated_from == amo.APPVERSIONS_ORIGINATED_FROM_DEVELOPER

    def test_compatibility_forbidden_range_android(self):
        request_data = {
            'version': {
                'upload': self.upload.uuid,
                'compatibility': {'android': {'min': '48.0', 'max': '*'}},
            }
        }
        response = self.request(data=request_data)
        assert response.status_code == 400, response.content
        assert response.data['version'] == {
            'compatibility': [
                'Invalid version range. For Firefox for Android, you may only pick a '
                'range that starts with version 120.0 or higher, or ends with lower '
                'than version 79.0a1.'
            ]
        }

        # Allowed range should work.
        request_data = {
            'version': {
                'upload': self.upload.uuid,
                'compatibility': {'android': {'min': '120.0', 'max': '*'}},
            }
        }
        response = self.request(data=request_data)
        assert response.status_code == 201, response.content


class TestAddonViewSetCreatePut(TestAddonViewSetCreate):
    client_request_verb = 'put'

    def setUp(self):
        super().setUp()
        self.set_guid('@webextension-guid')

    def set_guid(self, guid):
        self.guid = guid
        self.url = reverse_ns('addon-detail', kwargs={'pk': guid}, api_version='v5')

    def test_localized_xpi_default_locale_override(self):
        self.set_guid('notify-link-clicks-i18n@notzilla.org')
        super().test_localized_xpi_default_locale_override()

    def test_localized_xpi(self):
        self.set_guid('notify-link-clicks-i18n@notzilla.org')
        super().test_localized_xpi()

    def test_override_manifest_localization(self):
        self.set_guid('notify-link-clicks-i18n@notzilla.org')
        super().test_override_manifest_localization()

    def test_langpack(self):
        self.set_guid('langpack-de@firefox.mozilla.org')
        return super().test_langpack()

    def test_compatibility_langpack(self):
        self.set_guid('langpack-de@firefox.mozilla.org')
        return super().test_compatibility_langpack()

    def test_guid_mismatch(self):
        def parse_xpi_mock(pkg, *, addon, minimal, user, **kwargs):
            return {
                **parse_xpi(pkg, addon=addon, minimal=minimal, user=user),
                'guid': '@something',
            }

        with patch('olympia.files.utils.parse_xpi', side_effect=parse_xpi_mock):
            response = self.request()
        assert response.status_code == 400, response.content
        assert response.data == {
            'version': {
                'non_field_errors': ['GUID mismatch between the URL and manifest.']
            }
        }

    def test_no_guid_in_manifest(self):
        def parse_xpi_mock(pkg, *, addon, minimal, user, **kwargs):
            return {
                **parse_xpi(pkg, addon=addon, minimal=minimal, user=user),
                'guid': None,
            }

        with patch('olympia.files.utils.parse_xpi', side_effect=parse_xpi_mock):
            response = self.request()
        assert response.status_code == 400, response.content
        assert response.data == {
            'version': {
                'non_field_errors': ['A GUID must be specified in the manifest.']
            }
        }

    def test_only_guid_works_in_url(self):
        self.url = reverse_ns('addon-detail', kwargs={'pk': 'slug'}, api_version='v5')
        response = self.request()
        assert response.status_code == 404

    def test_duplicate_addon_id(self):
        # When using PUT, we automatically load the add-on if it exists, so we
        # aren't going to get the Duplicate add-on ID found error that we have
        # in the add-on creation test, but instead we're going to hit the
        # version already exists error, so this test is overridden to expect
        # that different error message.
        response = self.request()
        assert response.status_code == 201, response.content
        self.upload = self.get_upload(
            'webextension.xpi',
            user=self.user,
            source=amo.UPLOAD_SOURCE_ADDON_API,
            channel=amo.CHANNEL_UNLISTED,
        )
        self.minimal_data = {'version': {'upload': self.upload.uuid}}
        response = self.request()
        assert response.status_code == 409, response.status_code
        assert response.json() == {'version': ['Version 0.0.1 already exists.']}

    def test_addon_already_exists_add_version(self):
        addon = addon_factory(
            guid='@webextension-guid',
            version_kw={'version': '0.0.0'},
            users=[self.user],
            name='My Custom Addôn Nâme',
        )
        ActivityLog.objects.for_addons(addon).delete()  # Start fresh.
        response = self.request()
        assert response.status_code == 200
        data = response.data
        addon.reload()
        assert data['name'] == {'en-US': 'My Custom Addôn Nâme'}
        assert data['status'] == 'public'
        expected_version = addon.find_latest_version(channel=None)
        assert expected_version.channel == amo.CHANNEL_UNLISTED
        assert expected_version.version == '0.0.1'
        request = APIRequestFactory().get('/')
        request.version = 'v5'
        request.user = self.user
        expected_data = DeveloperAddonSerializer(
            context={'request': request}
        ).to_representation(addon)
        # The additional `version` property contains the version we just
        # uploaded.
        expected_data['version'] = DeveloperVersionSerializer(
            context={'request': request}
        ).to_representation(expected_version)
        assert dict(data) == dict(expected_data)
        assert (
            ActivityLog.objects.for_addons(addon)
            .filter(action=amo.LOG.ADD_VERSION.id)
            .count()
            == 1
        )

    def test_not_your_addon(self):
        # This test already exists below for POSTing new versions, but since
        # this can also be done via PUT when the add-on exists, test it here
        # too.
        addon = addon_factory(
            guid='@webextension-guid',  # Same guid we're using in URL
        )
        response = self.request()
        assert response.status_code == 403
        assert response.data['detail'] == (
            'You do not have permission to perform this action.'
        )
        assert addon.reload().versions.count() == 1


class TestAddonViewSetCreateJWTAuth(TestAddonViewSetCreate):
    client_class = APITestClientJWT


class TestAddonViewSetUpdate(AddonViewSetCreateUpdateMixin, TestCase):
    client_class = APITestClientSessionID
    SUCCESS_STATUS_CODE = 200
    client_request_verb = 'patch'

    def setUp(self):
        super().setUp()
        self.user = user_factory(read_dev_agreement=self.days_ago(0))
        self.addon = addon_factory(users=(self.user,))
        self.url = reverse_ns(
            'addon-detail', kwargs={'pk': self.addon.pk}, api_version='v5'
        )
        self.client.login_api(self.user)
        self.statsd_incr_mock = self.patch('olympia.addons.serializers.statsd.incr')

    def test_basic(self):
        response = self.request(data={'summary': {'en-US': 'summary update!'}})
        self.addon.reload()
        assert response.status_code == 200, response.content
        data = response.data
        assert data['name'] == {'en-US': self.addon.name}  # still the same
        assert data['summary'] == {'en-US': 'summary update!'}

        request = APIRequestFactory().get('/')
        request.version = 'v5'
        request.user = self.user

        expected_data = DeveloperAddonSerializer(
            context={'request': request}
        ).to_representation(self.addon)
        if 'version' in getattr(self, 'minimal_data', {}):
            expected_version = self.addon.find_latest_version(channel=None)
            expected_data['version'] = DeveloperVersionSerializer(
                context={'request': request}
            ).to_representation(expected_version)
        assert dict(data) == dict(expected_data)
        assert self.addon.summary == 'summary update!'
        alog = ActivityLog.objects.exclude(
            action__in=(
                amo.LOG.ADD_VERSION.id,
                amo.LOG.LOG_IN.id,
                amo.LOG.LOG_IN_API_TOKEN.id,
            )
        ).get()
        assert alog.user == self.user
        assert alog.action == amo.LOG.EDIT_PROPERTIES.id
        assert alog.details == ['summary']
        return data

    @override_settings(API_THROTTLING=False)
    def test_translated_fields(self):
        def patch(description_dict):
            return self.request(data={'description': description_dict})

        self.addon.reload()
        self.addon.description = 'description'
        self.addon.save()

        # change description in default_locale
        desc_en_us = 'description in English'
        response = patch({'en-US': desc_en_us})
        assert response.status_code == 200, response.content
        assert response.data['description'] == {'en-US': desc_en_us}
        assert self.addon.reload().description == desc_en_us
        self.addon.versions.first().update(version='0.123.1')

        # add description in other locale
        desc_es = 'descripción en español'
        response = patch({'es': desc_es})
        assert response.status_code == 200, response.content
        assert response.data['description'] == {'en-US': desc_en_us, 'es': desc_es}
        assert self.addon.reload().description == desc_en_us
        with self.activate('es'):
            assert self.addon.reload().description == desc_es
        with self.activate('fr'):
            assert self.addon.reload().description == desc_en_us  # default fallback
        self.addon.versions.first().update(version='0.123.2')

        # delete description in other locale (and add one)
        desc_fr = 'descriptif en français'
        response = patch({'es': None, 'fr': desc_fr})
        assert response.status_code == 200, response.content
        assert response.data['description'] == {'en-US': desc_en_us, 'fr': desc_fr}
        assert self.addon.reload().description == desc_en_us
        with self.activate('es'):
            assert self.addon.reload().description == desc_en_us  # default fallback
        with self.activate('fr'):
            assert self.addon.reload().description == desc_fr
            self.addon.versions.first().update(version='0.123.3')

        # delete description in default_locale but not "fr" - not allowed
        response = patch({'en-US': None})
        assert response.status_code == 400, response.content
        assert response.data == {
            'description': [
                'A value in the default locale of "en-US" is required if other '
                'translations are set.'
            ]
        }

        # but we can delete all translations (for a required==False field)
        response = patch({'en-US': None, 'fr': None})
        assert response.status_code == 200, response.content
        assert response.data['description'] is None
        self.addon = Addon.objects.get(id=self.addon.id)
        assert self.addon.description is None
        self.addon.versions.first().update(version='0.123.4')

        # And repeat the same call
        response = patch({'en-US': None, 'fr': None})
        assert response.status_code == 200, response.content
        self.addon.versions.first().update(version='0.123.5')

        # and then set it back again
        response = patch({'en-US': 'something'})
        assert response.status_code == 200, response.content
        assert response.data['description'] == {'en-US': 'something'}
        self.addon = Addon.objects.get(id=self.addon.id)
        assert self.addon.description == 'something'

    def test_not_authenticated(self):
        self.client.logout_api()
        response = self.request(data={'summary': {'en-US': 'summary update!'}})
        assert response.status_code == 401
        assert response.data == {
            'detail': 'Authentication credentials were not provided.'
        }
        assert self.addon.reload().summary != 'summary update!'

    def test_not_read_agreement(self):
        self.user.update(read_dev_agreement=None)
        response = self.request(data={'summary': {'en-US': 'summary update!'}})
        assert response.status_code in [401, 403]  # JWT auth is a 401; web auth is 403
        assert 'agreement' in response.data['detail'].lower()
        assert self.addon.reload().summary != 'summary update!'

    def test_not_your_addon(self):
        self.addon.addonuser_set.get(user=self.user).update(
            role=amo.AUTHOR_ROLE_DELETED
        )
        response = self.request(data={'summary': {'en-US': 'summary update!'}})
        assert response.status_code == 403
        assert response.data['detail'] == (
            'You do not have permission to perform this action.'
        )
        assert self.addon.reload().summary != 'summary update!'

    def test_waffle_flag_disabled(self):
        gates = {
            'v5': (
                gate
                for gate in settings.DRF_API_GATES['v5']
                if gate != 'addon-submission-api'
            )
        }
        with override_settings(DRF_API_GATES=gates):
            response = self.request(summary={'en-US': 'summary update!'})
        assert response.status_code == 403
        assert response.data == {
            'detail': 'You do not have permission to perform this action.'
        }
        assert self.addon.reload().summary != 'summary update!'

    def test_cant_update_version(self):
        response = self.request(version={'release_notes': {'en-US': 'new notes'}})
        assert response.status_code == 200, response.content
        assert self.addon.current_version.reload().release_notes != 'new notes'

    def test_update_categories(self):
        bookmarks_cat = CATEGORIES[amo.ADDON_EXTENSION]['bookmarks']
        tabs_cat = CATEGORIES[amo.ADDON_EXTENSION]['tabs']
        other_cat = CATEGORIES[amo.ADDON_EXTENSION]['other']
        AddonCategory.objects.filter(addon=self.addon).update(category_id=tabs_cat.id)
        assert self.addon.all_categories == [tabs_cat]

        response = self.request(data={'categories': ['bookmarks']})
        assert response.status_code == 200, response.content
        assert response.data['categories'] == ['bookmarks']
        self.addon = Addon.objects.get()
        assert self.addon.reload().all_categories == [bookmarks_cat]
        self.addon.versions.first().update(version='0.123.1')

        # repeat, but with the `other` category
        response = self.request(data={'categories': ['other']})
        assert response.status_code == 200, response.content
        assert response.data['categories'] == ['other']
        self.addon = Addon.objects.get()
        assert self.addon.reload().all_categories == [other_cat]

    def test_invalid_categories(self):
        tabs_cat = CATEGORIES[amo.ADDON_EXTENSION]['tabs']
        AddonCategory.objects.filter(addon=self.addon).update(category_id=tabs_cat.id)
        assert self.addon.all_categories == [tabs_cat]
        del self.addon.all_categories

        response = self.request(
            # performance is an android category
            data={'categories': ['performance']}
        )
        assert response.status_code == 400, response.content
        assert response.data == {'categories': ['Invalid category name.']}
        assert self.addon.reload().all_categories == [tabs_cat]

        response = self.request(
            # general is a firefox category, but for langpacks and dicts only
            data={'categories': ['general']},
        )
        assert response.status_code == 400, response.content
        assert response.data == {'categories': ['Invalid category name.']}
        assert self.addon.reload().all_categories == [tabs_cat]

    def test_set_slug_invalid(self):
        response = self.request(
            data={'slug': '!@!#!@##@$$%$#%#%$^^%&%'},
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'slug': [
                'Enter a valid “slug” consisting of letters, numbers, underscores or '
                'hyphens.'
            ]
        }

    def test_set_slug_denied(self):
        DeniedSlug.objects.create(name='denied-slug')
        response = self.request(
            data={'slug': 'denied-slug'},
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'slug': ['This slug cannot be used. Please choose another.']
        }

        response = self.request(
            data={'slug': '1234'},
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'slug': ['This slug cannot be used. Please choose another.']
        }

        # except if the slug was already in use (e.g. admin allowed)
        self.addon.update(slug='denied-slug')
        response = self.request(
            data={'slug': 'denied-slug'},
        )
        assert response.status_code == 200, response.content

    def test_set_slug_log(self):
        self.addon.update(slug='first-slug')
        response = self.request(
            data={'slug': 'second-slug'},
        )

        log_entry = ActivityLog.objects.filter(
            action=amo.LOG.ADDON_SLUG_CHANGED.id
        ).latest('pk')

        assert response.status_code == 200, response.content
        assert log_entry.user == self.user
        assert log_entry.arguments == [self.addon, 'first-slug', 'second-slug']
        assert 'slug from first-slug to second-slug' in str(log_entry)
        assert str(self.user.id) in str(log_entry)

    def test_set_extra_data(self):
        self.addon.description = 'Existing description'
        self.addon.save()
        patch_data = {
            'developer_comments': {'en-US': 'comments'},
            'homepage': {'en-US': 'https://my.home.page/'},
            # 'description'  # don't update - should retain existing
            'is_experimental': True,
            'name': {'en-US': 'new name'},
            'requires_payment': True,
            'slug': 'addoN-slug',
            'summary': {'en-US': 'new summary'},
            'support_email': {'en-US': 'email@me.me'},
            'support_url': {'en-US': 'https://my.home.page/support/'},
        }
        response = self.request(
            data=patch_data,
        )
        addon = Addon.objects.get()

        assert response.status_code == 200, response.content
        data = response.data
        assert data['name'] == {'en-US': 'new name'}
        assert addon.name == 'new name'
        assert data['developer_comments'] == {'en-US': 'comments'}
        assert addon.developer_comments == 'comments'
        assert data['homepage']['url'] == {'en-US': 'https://my.home.page/'}
        assert addon.homepage == 'https://my.home.page/'
        assert data['description'] == {'en-US': 'Existing description'}
        assert addon.description == 'Existing description'
        assert data['is_experimental'] is True
        assert addon.is_experimental is True
        assert data['requires_payment'] is True
        assert addon.requires_payment is True
        # addon.slug always gets slugified back to lowercase
        assert data['slug'] == 'addon-slug' == addon.slug
        assert data['summary'] == {'en-US': 'new summary'}
        assert addon.summary == 'new summary'
        assert data['support_email'] == {'en-US': 'email@me.me'}
        assert addon.support_email == 'email@me.me'
        assert data['support_url']['url'] == {'en-US': 'https://my.home.page/support/'}
        assert addon.support_url == 'https://my.home.page/support/'
        alog = ActivityLog.objects.exclude(
            action__in=(
                amo.LOG.ADD_VERSION.id,
                amo.LOG.LOG_IN.id,
                amo.LOG.LOG_IN_API_TOKEN.id,
                amo.LOG.ADDON_SLUG_CHANGED.id,
            )
        ).get()
        assert alog.user == self.user
        assert alog.action == amo.LOG.EDIT_PROPERTIES.id
        assert alog.details == list(patch_data.keys())

    def test_set_disabled(self):
        response = self.request(
            data={'is_disabled': True},
        )
        addon = Addon.objects.get()

        assert response.status_code == 200, response.content
        data = response.data
        assert data['is_disabled'] is True
        assert addon.is_disabled is True
        assert addon.disabled_by_user is True  # sets the user property
        alog = ActivityLog.objects.exclude(
            action__in=(
                amo.LOG.ADD_VERSION.id,
                amo.LOG.LOG_IN.id,
                amo.LOG.LOG_IN_API_TOKEN.id,
            )
        ).get()
        assert alog.user == self.user
        assert alog.action == amo.LOG.USER_DISABLE.id

    def test_set_enabled(self):
        addon = Addon.objects.get()
        # Confirm that a STATUS_DISABLED can't be overriden
        addon.update(status=amo.STATUS_DISABLED)
        response = self.request(
            data={'is_disabled': False},
        )
        addon.reload()
        assert response.status_code == 403  # Disabled addons can't be written to
        assert response.data['detail'] == (
            'You do not have permission to perform this action.'
        )

        # But a user disabled addon can be re-enabled
        addon.update(status=amo.STATUS_APPROVED, disabled_by_user=True)
        assert addon.is_disabled is True
        response = self.request(
            data={'is_disabled': False},
        )
        addon.reload()

        assert response.status_code == 200, response.content
        data = response.data
        assert data['is_disabled'] is False
        assert addon.is_disabled is False
        assert addon.disabled_by_user is False  # sets the user property
        alog = ActivityLog.objects.exclude(
            action__in=(
                amo.LOG.ADD_VERSION.id,
                amo.LOG.LOG_IN.id,
                amo.LOG.LOG_IN_API_TOKEN.id,
            )
        ).get()
        assert alog.user == self.user
        assert alog.action == amo.LOG.USER_ENABLE.id

    @override_settings(EXTERNAL_SITE_URL='https://amazing.site')
    def test_set_homepage_support_url_email(self):
        data = {
            'homepage': {'ro': '#%^%&&%^&^&^*'},
            'support_email': {'en-US': '#%^%&&%^&^&^*'},
            'support_url': {'fr': '#%^%&&%^&^&^*'},
        }
        response = self.request(
            data=data,
        )

        assert response.status_code == 400, response.content
        assert response.data == {
            'homepage': ['Enter a valid URL.'],
            'support_email': ['Enter a valid email address.'],
            'support_url': ['Enter a valid URL.'],
        }

        data = {
            'homepage': {'ro': f'{settings.EXTERNAL_SITE_URL}'},
            'support_url': {'fr': f'{settings.EXTERNAL_SITE_URL}/foo/'},
        }
        response = self.request(
            data=data,
        )
        msg = (
            'This field can only be used to link to external websites. '
            f'URLs on {settings.EXTERNAL_SITE_URL} are not allowed.'
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'homepage': [msg],
            'support_url': [msg],
        }

        data = {
            'homepage': {'ro': 'ftp://somewhere.com/foo'},
            'support_url': {'fr': 'ftp://somewhere.com'},
        }
        response = self.request(
            data=data,
        )
        msg = 'Enter a valid URL.'
        assert response.status_code == 400, response.content
        assert response.data == {
            'homepage': [msg],
            'support_url': [msg],
        }

    def test_set_tags(self):
        response = self.request(
            data={'tags': ['foo', 'bar']},
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'tags': {
                0: ['"foo" is not a valid choice.'],
                1: ['"bar" is not a valid choice.'],
            }
        }

        response = self.request(
            data={'tags': list(Tag.objects.values_list('tag_text', flat=True))},
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'tags': ['Ensure this field has no more than 10 elements.'],
        }

        # we're going to keep "zoom", but drop "security"
        Tag.objects.get(tag_text='zoom').add_tag(self.addon)
        Tag.objects.get(tag_text='security').add_tag(self.addon)

        response = self.request(
            data={'tags': ['zoom', 'music']},
        )
        assert response.status_code == 200, response.content
        assert response.data['tags'] == ['zoom', 'music']
        self.addon.reload()
        assert [tag.tag_text for tag in self.addon.tags.all()] == ['music', 'zoom']
        alogs = ActivityLog.objects.exclude(
            action__in=(
                amo.LOG.ADD_VERSION.id,
                amo.LOG.LOG_IN.id,
                amo.LOG.LOG_IN_API_TOKEN.id,
            )
        )
        assert len(alogs) == 2, [(a.action, a.details) for a in alogs]
        assert alogs[0].action == amo.LOG.REMOVE_TAG.id
        assert alogs[1].action == amo.LOG.ADD_TAG.id

    def _get_upload(self, filename):
        return SimpleUploadedFile(
            filename,
            open(get_image_path(filename), 'rb').read(),
            content_type=mimetypes.guess_type(filename)[0],
        )

    @mock.patch('olympia.addons.serializers.resize_icon.delay')
    @override_settings(API_THROTTLING=False)
    # We're mocking resize_icon because the async update of icon_hash messes up urls
    def test_upload_icon(self, resize_icon_mock):
        def patch_with_error(filename):
            response = self.request(
                data={'icon': _get_upload(filename)}, format='multipart'
            )
            assert response.status_code == 400, response.content
            return response.data['icon']

        assert patch_with_error('non-animated.gif') == [
            'Images must be either PNG or JPG.'
        ]
        assert patch_with_error('animated.png') == ['Images cannot be animated.']
        with override_settings(MAX_ICON_UPLOAD_SIZE=100):
            assert patch_with_error('preview.jpg') == [
                'Images must be smaller than 0MB',
                'Images must be square (same width and height).',
            ]

        assert self.addon.icon_type == ''
        response = self.request(
            data={'icon': _get_upload('mozilla-sq.png')},
            format='multipart',
        )
        assert response.status_code == 200, response.content

        self.addon.reload()
        assert response.data['icons'] == {
            '32': self.addon.get_icon_url(32),
            '64': self.addon.get_icon_url(64),
            '128': self.addon.get_icon_url(128),
        }
        assert self.addon.icon_type == 'image/png'
        resize_icon_mock.assert_called_with(
            f'{self.addon.get_icon_dir()}/{self.addon.id}-original.png',
            self.addon.id,
            amo.ADDON_ICON_SIZES,
            set_modified_on=self.addon.serializable_reference(),
        )
        assert os.path.exists(
            os.path.join(self.addon.get_icon_dir(), f'{self.addon.id}-original.png')
        )
        alog = ActivityLog.objects.exclude(
            action__in=(amo.LOG.LOG_IN.id, amo.LOG.LOG_IN_API_TOKEN.id)
        ).get()
        assert alog.user == self.user
        assert alog.action == amo.LOG.CHANGE_MEDIA.id

    @mock.patch('olympia.addons.serializers.remove_icons')
    def _test_delete_icon(self, request_data, request_format, remove_icons_mock):
        self.addon.update(icon_type='image/png')
        response = self.request(data=request_data, format=request_format)
        assert response.status_code == 200, response.content

        self.addon.reload()
        assert response.data['icons'] == {
            '32': self.addon.get_default_icon_url(32),
            '64': self.addon.get_default_icon_url(64),
            '128': self.addon.get_default_icon_url(128),
        }
        assert self.addon.icon_type == ''
        remove_icons_mock.assert_called()
        alog = ActivityLog.objects.exclude(
            action__in=(
                amo.LOG.ADD_VERSION.id,
                amo.LOG.LOG_IN.id,
                amo.LOG.LOG_IN_API_TOKEN.id,
            )
        ).get()
        assert alog.user == self.user
        assert alog.action == amo.LOG.CHANGE_MEDIA.id

    def test_delete_icon_json(self):
        self._test_delete_icon({'icon': None}, None)

    def test_delete_icon_formdata(self):
        self._test_delete_icon({'icon': ''}, 'multipart')

    def _test_metadata_content_review(self):
        response = self.request(
            data={'name': {'en-US': 'new name'}, 'summary': {'en-US': 'new summary'}},
        )
        assert response.status_code == 200

    @mock.patch('olympia.addons.serializers.fetch_translations_from_addon')
    def test_metadata_content_review_unlisted(self, fetch_mock):
        self.make_addon_unlisted(self.addon)
        AddonApprovalsCounter.approve_content_for_addon(addon=self.addon)
        old_content_review = AddonApprovalsCounter.objects.get(
            addon=self.addon
        ).last_content_review
        assert old_content_review

        self._test_metadata_content_review()

        fetch_mock.assert_not_called()
        with self.assertRaises(AssertionError):
            self.statsd_incr_mock.assert_any_call(
                'addons.submission.metadata_content_review_triggered'
            )
        assert (
            old_content_review
            == AddonApprovalsCounter.objects.get(addon=self.addon).last_content_review
        )

    def test_metadata_change_triggers_content_review(self):
        AddonApprovalsCounter.approve_content_for_addon(addon=self.addon)
        assert AddonApprovalsCounter.objects.get(addon=self.addon).last_content_review

        self._test_metadata_content_review()

        self.addon.reload()
        # last_content_review should have been reset
        assert not AddonApprovalsCounter.objects.get(
            addon=self.addon
        ).last_content_review
        self.statsd_incr_mock.assert_any_call(
            'addons.submission.metadata_content_review_triggered'
        )

    def test_metadata_change_same_content(self):
        AddonApprovalsCounter.approve_content_for_addon(addon=self.addon)
        old_content_review = AddonApprovalsCounter.objects.get(
            addon=self.addon
        ).last_content_review
        assert old_content_review
        self.addon.name = {'en-US': 'new name'}
        self.addon.summary = {'en-US': 'new summary'}
        self.addon.save()

        self._test_metadata_content_review()

        with self.assertRaises(AssertionError):
            self.statsd_incr_mock.assert_any_call(
                'addons.submission.metadata_content_review_triggered'
            )
        assert (
            old_content_review
            == AddonApprovalsCounter.objects.get(addon=self.addon).last_content_review
        )

    def test_metadata_required(self):
        # name and summary are treated as required for updates
        data = {'name': {'en-US': None}, 'summary': {'en-US': None}, 'categories': {}}
        response = self.request(data=data)
        assert response.status_code == 400
        assert response.data == {
            'name': ['A value in the default locale of "en-US" is required.'],
            'summary': ['A value in the default locale of "en-US" is required.'],
            'categories': ['This field is required.'],
        }

        # this requirement isn't enforced for addons without listed versions though
        self.addon.current_version.update(channel=amo.CHANNEL_UNLISTED)
        response = self.request(data=data)
        assert response.status_code == 200

    def test_default_locale(self):
        response = self.request(data={'default_locale': 'zz'})
        assert response.status_code == 400
        assert response.data == {'default_locale': ['"zz" is not a valid choice.']}

        Translation.objects.create(
            id=self.addon.summary_id, locale='fr', localized_string='summary Française'
        )
        self.addon.description = 'description!'
        self.addon.save()

        # failure cases:
        # A field is required and doesn't already have a value in new default
        # B field is set to None in update
        # C field isn't required, but has other translations already
        # D field isn't required, but has other translations provided
        response = self.request(
            data={
                'default_locale': 'fr',
                # A no name, doesn't have a value in fr
                'summary': {'fr': None},  # B summary has a value, but None would clear
                # C no description, has a value in en-US already
                'support_url': {'de': 'https://de.support.test/'},  # D
            },
        )
        assert response.status_code == 400, response.data
        error_string = 'A value in the default locale of "fr" is required.'
        assert response.data == {
            'name': [error_string],
            'summary': [error_string],
            'description': [error_string],
            'support_url': [error_string],
        }

        self.addon.update(description=None)
        # success cases - tested with different fields in the patch request:
        # A field is provided with a value in new default in the postdata
        # B field already has a value in new default - we created the Translation above
        # C field isn't required and has no other translations - we set description=None
        response = self.request(
            data={
                'default_locale': 'fr',
                'name': {'fr': 'nom française'},  # A
                # B no summary, but does have a value in fr already
                # C no description, and isn't required
            },
        )
        assert response.status_code == 200, response.data
        self.addon.reload()
        assert self.addon.default_locale == 'fr'


class TestAddonViewSetUpdatePut(UploadMixin, TestAddonViewSetUpdate):
    client_request_verb = 'put'

    def setUp(self):
        super().setUp()
        self.addon.update(guid='@webextension-guid')
        self.addon.current_version.update(version='0.0.0.99')
        self.url = reverse_ns(
            'addon-detail', kwargs={'pk': self.addon.guid}, api_version='v5'
        )

    @property
    def minimal_data(self):
        # we generate this dynamically as some of the tests do repeated requests
        upload = self.get_upload(
            'webextension.xpi',
            user=self.user,
            source=amo.UPLOAD_SOURCE_ADDON_API,
            channel=getattr(self, 'channel', amo.CHANNEL_UNLISTED),
        )
        return {'version': {'upload': upload.uuid}}

    def test_basic(self):
        self.addon.current_version.update(license=None)
        version_data = super().test_basic()['latest_unlisted_version']
        assert version_data['license'] is None
        assert version_data['compatibility'] == {
            'firefox': {'max': '*', 'min': '42.0'},
        }
        assert self.addon.versions.count() == 2
        version = self.addon.find_latest_version(channel=None)
        assert version.channel == amo.CHANNEL_UNLISTED
        self.statsd_incr_mock.assert_any_call('addons.submission.version.unlisted')

    def test_basic_listed(self):
        license = self.addon.current_version.license
        self.channel = amo.CHANNEL_LISTED
        self.addon.current_version.file.update(status=amo.STATUS_DISABLED)
        self.addon.update_status()
        assert self.addon.status == amo.STATUS_NULL

        version_data = super().test_basic()['current_version']
        assert version_data['license'] == CompactLicenseSerializer().to_representation(
            license
        )
        assert version_data['compatibility'] == {
            'firefox': {'max': '*', 'min': '42.0'},
        }
        assert self.addon.versions.count() == 2
        version = self.addon.find_latest_version(channel=None)
        assert version.channel == amo.CHANNEL_LISTED
        assert self.addon.status == amo.STATUS_NOMINATED
        self.statsd_incr_mock.assert_any_call('addons.submission.version.listed')

    def test_listed_metadata_missing(self):
        self.channel = amo.CHANNEL_LISTED
        self.addon.current_version.update(license=None)
        self.addon.set_categories([])
        response = self.request()
        assert response.status_code == 400, response.content
        assert response.data == {
            'version': {
                'license': [
                    'This field, or custom_license, is required for listed versions.'
                ],
            }
        }

        # If the license is set we'll get further validation errors from about the addon
        # fields that aren't set.
        license = License.objects.create(builtin=2)
        response = self.client.put(
            self.url,
            data={
                'version': {
                    'upload': self.minimal_data['version']['upload'],
                    'license': license.slug,
                }
            },
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'categories': ['This field is required for add-ons with listed versions.']
        }

        assert self.addon.reload().versions.count() == 1

    def test_license_inherited_from_previous_version(self):
        self.channel = amo.CHANNEL_LISTED
        previous_license = self.addon.current_version.license
        super().test_basic()
        assert self.addon.versions.count() == 2
        version = self.addon.find_latest_version(channel=None)
        assert version.license == previous_license
        self.statsd_incr_mock.assert_any_call('addons.submission.version.listed')

    def test_only_guid_works_in_url(self):
        self.url = reverse_ns(
            'addon-detail', kwargs={'pk': self.addon.slug}, api_version='v5'
        )
        response = self.request()
        assert response.status_code == 404

    def test_upload_icon(self):
        # It's not possible to send formdata format with nested json
        pass

    def test_delete_icon_formdata(self):
        # It's not possible to send formdata format with nested json
        pass

    def test_cant_update_version(self):
        # With put you *can* update version
        pass


class TestAddonViewSetUpdateJWTAuth(TestAddonViewSetUpdate):
    client_class = APITestClientJWT


class TestAddonViewSetDelete(TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        super().setUp()
        self.user = user_factory(read_dev_agreement=self.days_ago(0))
        self.addon = addon_factory(users=(self.user,))
        self.url = reverse_ns(
            'addon-detail', kwargs={'pk': self.addon.pk}, api_version='v5'
        )

    @freeze_time()
    def test_delete_confirm(self):
        delete_confirm_url = f'{self.url}delete_confirm/'

        response = self.client.get(delete_confirm_url)
        assert response.status_code == 401

        self.client.login_api(self.user)
        response = self.client.get(delete_confirm_url)
        assert response.status_code == 200
        assert response.data == {
            'delete_confirm': DeleteTokenSigner().generate(self.addon.id)
        }

        # confirm we didn't delete the addon already
        self.addon.reload()
        assert self.addon.status == amo.STATUS_APPROVED

    def _perform_delete_request(self, status_code):
        token = DeleteTokenSigner().generate(self.addon.id)
        response = self.client.delete(f'{self.url}?delete_confirm={token}')
        assert response.status_code == status_code, response.content
        self.addon.reload()
        return response

    def test_delete(self):
        response = self.client.delete(self.url)
        assert response.status_code == 401

        self.client.login_api(self.user)
        response = self.client.delete(self.url)
        assert response.status_code == 400
        assert response.data == [
            '"delete_confirm" token must be supplied for add-on delete.'
        ]

        response = self.client.delete(f'{self.url}?delete_confirm=foo')
        assert response.status_code == 400
        assert response.data == ['"delete_confirm" token is invalid.']

        self._perform_delete_request(204)
        assert self.addon.status == amo.STATUS_DELETED

    def test_delete_prevented_for_developer_role(self):
        AddonUser.objects.get(addon=self.addon, user=self.user).update(
            role=amo.AUTHOR_ROLE_DEV
        )
        # edge-case: user is an owner of a *different* add-on too
        addon_factory(users=(self.user,))
        self.client.login_api(self.user)
        response = self._perform_delete_request(403)
        assert response.data == {
            'detail': 'You do not have permission to perform this action.',
            'is_disabled_by_developer': False,
            'is_disabled_by_mozilla': False,
        }
        assert self.addon.status == amo.STATUS_APPROVED


class TestVersionViewSetDetail(AddonAndVersionViewSetDetailMixin, TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        super().setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(),
            name='My Addôn',
            slug='my-addon',
            version_kw={'version': '1.0'},
        )

        # Don't use addon.current_version, changing its state as we do in
        # the tests might render the add-on itself inaccessible.
        self.version = version_factory(addon=self.addon, version='2.0')
        self._set_tested_url(self.addon.pk)

    def _test_url(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert (
            response['Vary']
            == 'origin, Accept-Encoding, X-Country-Code, Accept-Language'
        )
        result = json.loads(force_str(response.content))
        assert result['id'] == self.version.pk
        assert result['version'] == self.version.version
        assert result['license']
        assert result['license']['name']
        assert result['license']['text']

    def _set_tested_url(self, param):
        self.url = reverse_ns(
            'addon-version-detail', kwargs={'addon_pk': param, 'pk': self.version.pk}
        )

    def test_version_get_not_found(self):
        self.url = reverse_ns(
            'addon-version-detail',
            kwargs={'addon_pk': self.addon.pk, 'pk': self.version.pk + 42},
        )
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_lookup_by_version_number(self):
        self.url = reverse_ns(
            'addon-version-detail',
            kwargs={'addon_pk': self.addon.pk, 'pk': self.version.version},
        )
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_lookup_by_version_number_not_found(self):
        # Add a different add-on with the version number we'll be using in the
        # URL, making sure we don't accidentally find it.
        addon_factory(version_kw={'version': '3.0'})
        self.url = reverse_ns(
            'addon-version-detail',
            kwargs={'addon_pk': self.addon.pk, 'pk': '3.0'},
        )
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_lookup_by_version_number_garbage(self):
        self.url = reverse_ns(
            'addon-version-detail',
            kwargs={'addon_pk': self.addon.pk, 'pk': 'somestring'},
        )
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_lookup_by_version_number_integer_doesnt_work(self):
        # Set the version number to an integer (no dots) that isn't the pk.
        self.version.update(version=str(self.version.pk + 2))
        self.url = reverse_ns(
            'addon-version-detail',
            kwargs={'addon_pk': self.addon.pk, 'pk': self.version.version},
        )
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_lookup_by_version_number_integer_with_v_prefix(self):
        # Set the version number to an integer (no dots) that isn't the pk.
        self.version.update(version=str(self.version.pk + 2))
        self.url = reverse_ns(
            'addon-version-detail',
            kwargs={'addon_pk': self.addon.pk, 'pk': f'v{self.version.version}'},
        )
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_disabled_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.file.update(status=amo.STATUS_DISABLED)
        self._test_url()

    def test_disabled_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        self.version.file.update(status=amo.STATUS_DISABLED)
        self._test_url()

    def test_disabled_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self.version.file.update(status=amo.STATUS_DISABLED)
        self._test_url()

    def test_disabled_version_anonymous(self):
        self.version.file.update(status=amo.STATUS_DISABLED)
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_disabled_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.file.update(status=amo.STATUS_DISABLED)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_deleted_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.delete()
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_deleted_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        self.version.delete()
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_deleted_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self.version.delete()
        self._test_url()

    def test_deleted_version_anonymous(self):
        self.version.delete()
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_deleted_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.delete()
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_unlisted_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_unlisted_version_unlisted_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.client.login_api(user)
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        self._test_url()

    def test_unlisted_version_unlisted_viewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'ReviewerTools:ViewUnlisted')
        self.client.login_api(user)
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        self._test_url()

    def test_unlisted_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        self._test_url()

    def test_unlisted_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        self._test_url()

    def test_unlisted_version_anonymous(self):
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_unlisted_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_developer_version_serializer_used_for_authors(self):
        self.version.update(source='src.zip')
        # not logged in
        assert 'source' not in self.client.get(self.url).data

        user = UserProfile.objects.create(username='user')
        self.client.login_api(user)

        # logged in but not an author
        assert 'source' not in self.client.get(self.url).data

        AddonUser.objects.create(user=user, addon=self.addon)

        # the field is present when the user is an author of the add-on.
        assert 'source' in self.client.get(self.url).data


class VersionViewSetCreateUpdateMixin(RequestMixin):
    SUCCESS_STATUS_CODE = 200

    def _submit_source(self, filepath, error=False):
        raise NotImplementedError

    def _generate_source_tar(self, suffix='.tar.gz', data=b't' * (2**21), mode=None):
        source = tempfile.NamedTemporaryFile(suffix=suffix, dir=settings.TMP_PATH)
        if mode is None:
            mode = 'w:bz2' if suffix.endswith('.tar.bz2') else 'w:gz'
        with tarfile.open(fileobj=source, mode=mode) as tar_file:
            tar_info = tarfile.TarInfo('foo')
            tar_info.size = len(data)
            tar_file.addfile(tar_info, io.BytesIO(data))

        source.seek(0)
        return source

    def _generate_source_zip(
        self, suffix='.zip', data='z' * (2**21), compression=zipfile.ZIP_DEFLATED
    ):
        source = tempfile.NamedTemporaryFile(suffix=suffix, dir=settings.TMP_PATH)
        with zipfile.ZipFile(source, 'w', compression=compression) as zip_file:
            zip_file.writestr('foo', data)
        source.seek(0)
        return source

    @mock.patch('olympia.addons.views.log')
    def test_source_zip(self, log_mock):
        is_update = hasattr(self, 'version')
        _, version = self._submit_source(
            self.file_path('webextension_with_image.zip'),
        )
        assert version.source
        assert str(version.source).endswith('.zip')
        mode = '0%o' % (os.stat(version.source.path)[stat.ST_MODE])
        assert mode == '0100644'
        assert log_mock.info.call_count == 4
        assert log_mock.info.call_args_list[0][0] == (
            (
                'update, source upload received, addon.slug: %s, version.id: %s',
                version.addon.slug,
                version.id,
            )
            if is_update
            else (
                'create, source upload received, addon.slug: %s',
                version.addon.slug,
            )
        )
        assert log_mock.info.call_args_list[1][0] == (
            (
                'update, serializer loaded, addon.slug: %s, version.id: %s',
                version.addon.slug,
                version.id,
            )
            if is_update
            else (
                'create, serializer loaded, addon.slug: %s',
                version.addon.slug,
            )
        )
        assert log_mock.info.call_args_list[2][0] == (
            (
                'update, serializer validated, addon.slug: %s, version.id: %s',
                version.addon.slug,
                version.id,
            )
            if is_update
            else (
                'create, serializer validated, addon.slug: %s',
                version.addon.slug,
            )
        )
        assert log_mock.info.call_args_list[3][0] == (
            (
                'update, data saved, addon.slug: %s, version.id: %s',
                version.addon.slug,
                version.id,
            )
            if is_update
            else (
                'create, data saved, addon.slug: %s',
                version.addon.slug,
            )
        )
        log = ActivityLog.objects.get(action=amo.LOG.SOURCE_CODE_UPLOADED.id)
        assert log.user == self.user
        assert log.details is None
        assert log.arguments == [self.addon, version]

    def test_source_targz(self):
        _, version = self._submit_source(self.file_path('webextension_no_id.tar.gz'))
        assert version.source
        assert str(version.source).endswith('.tar.gz')
        mode = '0%o' % (os.stat(version.source.path)[stat.ST_MODE])
        assert mode == '0100644'

    def test_source_tgz(self):
        _, version = self._submit_source(self.file_path('webextension_no_id.tgz'))
        assert version.source
        assert str(version.source).endswith('.tgz')
        mode = '0%o' % (os.stat(version.source.path)[stat.ST_MODE])
        assert mode == '0100644'

    def test_source_tarbz2(self):
        _, version = self._submit_source(
            self.file_path('webextension_no_id.tar.bz2'),
        )
        assert version.source
        assert str(version.source).endswith('.tar.bz2')
        mode = '0%o' % (os.stat(version.source.path)[stat.ST_MODE])
        assert mode == '0100644'

    def test_with_bad_source_extension(self):
        response, version = self._submit_source(
            self.file_path('webextension_crx3.crx'),
            error=True,
        )
        assert response.data['source'] == [
            'Unsupported file type, please upload an archive file '
            '(.zip, .tar.gz, .tgz, .tar.bz2).'
        ]
        assert not version or not version.source
        self.addon.reload()
        assert not ActivityLog.objects.filter(
            action=amo.LOG.SOURCE_CODE_UPLOADED.id
        ).exists()

    def test_with_bad_source_broken_archive(self):
        source = self._generate_source_zip(
            data='Hello World', compression=zipfile.ZIP_STORED
        )
        data = source.read().replace(b'Hello World', b'dlroW olleH')
        source.seek(0)  # First seek to rewrite from the beginning
        source.write(data)
        source.seek(0)  # Second seek to reset like it's fresh.
        # Still looks like a zip at first glance.
        assert zipfile.is_zipfile(source)
        source.seek(0)  # Last seek to reset source descriptor before posting.
        with open(source.name, 'rb'):
            response, version = self._submit_source(
                source.name,
                error=True,
            )
        assert response.data['source'] == ['Invalid or broken archive.']
        self.addon.reload()
        assert not version or not version.source
        assert not ActivityLog.objects.filter(
            action=amo.LOG.SOURCE_CODE_UPLOADED.id
        ).exists()

    def test_with_bad_source_broken_archive_compressed_tar(self):
        source = self._generate_source_tar()
        with open(source.name, 'r+b') as fobj:
            fobj.truncate(512)
        # Still looks like a tar at first glance.
        assert tarfile.is_tarfile(source.name)
        # Re-open and post.
        with open(source.name, 'rb'):
            response, version = self._submit_source(
                source.name,
                error=True,
            )
        assert response.data['source'] == ['Invalid or broken archive.']
        self.addon.reload()
        assert not version or not version.source
        assert not ActivityLog.objects.filter(
            action=amo.LOG.SOURCE_CODE_UPLOADED.id
        ).exists()

    def test_activity_log_each_time(self):
        _, version = self._submit_source(
            self.file_path('webextension_with_image.zip'),
        )
        assert version.source
        assert str(version.source).endswith('.zip')
        mode = '0%o' % (os.stat(version.source.path)[stat.ST_MODE])
        assert mode == '0100644'

        log = ActivityLog.objects.get(action=amo.LOG.SOURCE_CODE_UPLOADED.id)
        assert log.user == self.user
        assert log.details is None
        assert log.arguments == [self.addon, version]

    @override_settings(API_THROTTLING=False)
    def test_custom_license_needs_name_and_text(self):
        response = self.request(custom_license={})
        assert response.status_code == 400, response.content
        assert response.data == {
            'custom_license': {
                'name': ['This field is required.'],
                'text': ['This field is required.'],
            }
        }

        response = self.request(custom_license={'name': {'en-US': 'foo'}})
        assert response.status_code == 400, response.content
        assert response.data == {
            'custom_license': {'text': ['This field is required.']}
        }

        response = self.request(custom_license={'text': {'en-US': 'baa'}})
        assert response.status_code == 400, response.content
        assert response.data == {
            'custom_license': {'name': ['This field is required.']}
        }

        # Check null values are also ignored
        response = self.request(
            custom_license={'name': {'en-US': None}, 'text': {'en-US': None}}
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'custom_license': {
                'name': ['A value in the default locale of "en-US" is required.'],
                'text': ['A value in the default locale of "en-US" is required.'],
            }
        }

    def test_custom_license_needs_name_and_text_empty_ignored(self):
        # Check empty l10n is also ignored
        response = self.request(custom_license={'name': {}, 'text': {}})
        assert response.status_code == 400, response.content
        assert response.data == {
            'custom_license': {
                'name': ['This field is required.'],
                'text': ['This field is required.'],
            }
        }

    def test_custom_license_needs_default_locale_value(self):
        response = self.request(
            custom_license={'name': {'it': 'test'}, 'text': {'it': 'test'}}
        )
        assert response.status_code == 400, response.content
        error_string = 'A value in the default locale of "en-US" is required.'
        assert response.data == {
            'custom_license': {
                'name': [error_string],
                'text': [error_string],
            }
        }

    def test_compatibility_list(self):
        response = self.request(compatibility=[])
        assert response.status_code == 400, response.content
        assert response.data == {'compatibility': ['Invalid value']}

        response = self.request(compatibility=['foo', 'android'])
        assert response.status_code == 400, response.content
        assert response.data == {'compatibility': ['Invalid app specified']}

        response = self.request(compatibility=['firefox', 'android'])
        assert response.status_code == self.SUCCESS_STATUS_CODE, response.content
        data = response.data
        self.addon.reload()
        assert self.addon.versions.count() == (1 if hasattr(self, 'version') else 2)
        version = self.addon.find_latest_version(channel=None)
        assert data['compatibility'] == {
            'android': {'max': '*', 'min': amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY},
            'firefox': {'max': '*', 'min': '42.0'},
        }
        assert list(version.compatible_apps.keys()) == [amo.FIREFOX, amo.ANDROID]
        for avs in version.compatible_apps.values():
            assert avs.originated_from == amo.APPVERSIONS_ORIGINATED_FROM_DEVELOPER

    def test_compatibility_dict(self):
        response = self.request(compatibility={})
        assert response.status_code == 400, response.content
        assert response.data == {'compatibility': ['Invalid value']}

        response = self.request(compatibility={'firefox': {'min': '61.0'}, 'foo': {}})
        assert response.status_code == 400, response.content
        assert response.data == {'compatibility': ['Invalid app specified']}

        # 61.0 (DEFAULT_WEBEXT_DICT_MIN_VERSION_FIREFOX) should be valid.
        response = self.request(
            compatibility={'firefox': {'min': '61.0'}, 'android': {}}
        )
        assert response.status_code == self.SUCCESS_STATUS_CODE, response.content
        data = response.data
        self.addon.reload()
        assert self.addon.versions.count() == (1 if hasattr(self, 'version') else 2)
        version = self.addon.find_latest_version(channel=None)
        assert data['compatibility'] == {
            # android was specified but with an empty dict, so gets the default
            # corrected to account for general availability.
            'android': {'max': '*', 'min': amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY},
            # firefox max wasn't specified, so is the default max app version
            'firefox': {'max': '*', 'min': '61.0'},
        }
        assert list(version.compatible_apps.keys()) == [amo.FIREFOX, amo.ANDROID]
        for avs in version.compatible_apps.values():
            assert avs.originated_from == amo.APPVERSIONS_ORIGINATED_FROM_DEVELOPER

    def test_compatibility_dict_high_appversion_that_exists(self):
        # APPVERSION_HIGHER_THAN_EVERYTHING_ELSE ('121.0') is valid per setUpTestData()
        response = self.request(
            compatibility={
                'firefox': {'min': self.APPVERSION_HIGHER_THAN_EVERYTHING_ELSE}
            }
        )
        assert response.status_code == self.SUCCESS_STATUS_CODE, response.content
        data = response.data
        self.addon.reload()
        assert self.addon.versions.count() == (1 if hasattr(self, 'version') else 2)
        version = self.addon.find_latest_version(channel=None)
        assert data['compatibility'] == {
            # firefox max wasn't specified, so is the default max app version
            'firefox': {'max': '*', 'min': self.APPVERSION_HIGHER_THAN_EVERYTHING_ELSE},
        }
        assert list(version.compatible_apps.keys()) == [amo.FIREFOX]

    def test_compatibility_invalid_versions(self):
        # 99 doesn't exist as an appversion
        response = self.request(compatibility={'firefox': {'max': '99.0'}})
        assert response.status_code == 400, response.content
        assert response.data == {'compatibility': ['Unknown max app version specified']}

        # `*` isn't a valid min
        response = self.request(compatibility={'firefox': {'min': '*'}})
        assert response.status_code == 400, response.content
        assert response.data == {'compatibility': ['Unknown min app version specified']}

        # Even when it exists, any version ending in `.*` isn't a valid min either
        AppVersion.objects.create(application=amo.FIREFOX.id, version='61.*')
        response = self.request(compatibility={'firefox': {'min': '61.*'}})
        assert response.status_code == 400, response.content
        assert response.data == {'compatibility': ['Unknown min app version specified']}

    def test_compatibility_forbidden_range_android(self):
        response = self.request(compatibility={'android': {'min': '48.0', 'max': '*'}})
        assert response.status_code == 400, response.content
        assert response.data == {
            'compatibility': [
                'Invalid version range. For Firefox for Android, you may only pick a '
                'range that starts with version 120.0 or higher, or ends with lower '
                'than version 79.0a1.'
            ]
        }

        # Recommended add-ons for Android don't have that restriction.
        self.make_addon_promoted(self.addon, RECOMMENDED, approve_version=True)
        response = self.request(compatibility={'android': {'min': '48.0', 'max': '*'}})
        assert response.status_code == self.SUCCESS_STATUS_CODE, response.content

    def test_compatibility_forbidden_range_android_only_min_specified(self):
        response = self.request(compatibility={'android': {'min': '48.0'}})
        assert response.status_code == 400, response.content
        assert response.data == {
            'compatibility': [
                'Invalid version range. For Firefox for Android, you may only pick a '
                'range that starts with version 120.0 or higher, or ends with lower '
                'than version 79.0a1.'
            ]
        }

        # Recommended add-ons for Android don't have that restriction.
        self.make_addon_promoted(self.addon, RECOMMENDED, approve_version=True)
        response = self.request(compatibility={'android': {'min': '48.0'}})
        assert response.status_code == self.SUCCESS_STATUS_CODE, response.content

    @staticmethod
    def _parse_xpi_mock(pkg, *, addon, minimal, user, **kwargs):
        return {
            **parse_xpi(pkg, addon=addon, minimal=minimal, user=user),
            'type': addon.type,
        }

    def test_compatibility_dictionary_list(self):
        self.addon.update(type=amo.ADDON_DICT)
        with patch('olympia.files.utils.parse_xpi', side_effect=self._parse_xpi_mock):
            response = self.request(compatibility=['firefox', 'android'])
        assert response.status_code == 400, response.content
        assert response.data == {
            'compatibility': [
                'This type of add-on does not allow custom compatibility.'
            ]
        }

    def test_compatibility_dictionary_dict(self):
        self.addon.update(type=amo.ADDON_DICT)

        with patch('olympia.files.utils.parse_xpi', side_effect=self._parse_xpi_mock):
            response = self.request(
                compatibility={'firefox': {'min': '61.0'}, 'android': {}}
            )
        assert response.status_code == 400, response.content
        assert response.data == {
            'compatibility': [
                'This type of add-on does not allow custom compatibility.'
            ]
        }

    def test_basic_dictionary(self):
        self.addon.update(type=amo.ADDON_DICT)
        with patch('olympia.files.utils.parse_xpi', side_effect=self._parse_xpi_mock):
            self.test_basic()

    def test_compatibility_langpack(self):
        self.addon.update(type=amo.ADDON_LPAPP)

        with patch('olympia.files.utils.parse_xpi', side_effect=self._parse_xpi_mock):
            response = self.request(
                compatibility={'firefox': {'min': '61.0'}, 'android': {}}
            )
        # This is allowed for the moment but should be prevented by
        # https://github.com/mozilla/addons-server/issues/21275
        assert response.status_code == self.SUCCESS_STATUS_CODE, response.content

    @override_settings(API_THROTTLING=False)
    def test_cannot_specify_invalid_license_slug(self):
        License.objects.create(builtin=LICENSE_GPL3.builtin)

        for invalid_slug in ('made-up-slug', 0, {}, []):
            response = self.request(license=invalid_slug)
            assert response.status_code == 400
            assert response.data == {
                'license': [f'License with slug={invalid_slug} does not exist.']
            }

        assert (
            self.request(license=LICENSE_GPL3.slug).status_code
            == self.SUCCESS_STATUS_CODE
        )


class TestVersionViewSetCreate(UploadMixin, VersionViewSetCreateUpdateMixin, TestCase):
    client_class = APITestClientSessionID
    client_request_verb = 'post'
    SUCCESS_STATUS_CODE = 201
    APPVERSION_HIGHER_THAN_EVERYTHING_ELSE = '121.0'

    @classmethod
    def setUpTestData(cls):
        versions = {
            amo.DEFAULT_WEBEXT_MIN_VERSION,
            amo.DEFAULT_WEBEXT_MIN_VERSION_NO_ID,
            amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID,
            amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX,
            amo.DEFAULT_WEBEXT_DICT_MIN_VERSION_FIREFOX,
            amo.DEFAULT_WEBEXT_MAX_VERSION,
            amo.DEFAULT_WEBEXT_MIN_VERSION_MV3_FIREFOX,
            amo.DEFAULT_WEBEXT_MIN_VERSION_GECKO_ANDROID,
            amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY,
            cls.APPVERSION_HIGHER_THAN_EVERYTHING_ELSE,
        }
        for version in versions:
            AppVersion.objects.get_or_create(
                application=amo.FIREFOX.id, version=version
            )
            AppVersion.objects.get_or_create(
                application=amo.ANDROID.id, version=version
            )

    def setUp(self):
        super().setUp()
        self.user = user_factory(read_dev_agreement=self.days_ago(0))
        self.upload = self.get_upload(
            'webextension.xpi',
            user=self.user,
            source=amo.UPLOAD_SOURCE_ADDON_API,
            channel=amo.CHANNEL_UNLISTED,
        )
        self.addon = addon_factory(
            users=(self.user,),
            guid='@webextension-guid',
            version_kw={'version': '0.0.0.999'},
        )
        self.url = reverse_ns(
            'addon-version-list',
            kwargs={'addon_pk': self.addon.slug},
            api_version='v5',
        )
        self.client.login_api(self.user)
        self.license = License.objects.create(builtin=2)
        self.minimal_data = {'upload': self.upload.uuid}
        self.statsd_incr_mock = self.patch('olympia.addons.serializers.statsd.incr')

    def test_basic_unlisted(self):
        response = self.client.post(
            self.url,
            data=self.minimal_data,
            HTTP_USER_AGENT='web-ext/12.34',
        )
        assert response.status_code == 201, response.content
        data = response.data
        assert data['license'] is None
        assert data['compatibility'] == {
            'firefox': {'max': '*', 'min': '42.0'},
        }
        self.addon.reload()
        assert self.addon.versions.count() == 2
        version = self.addon.find_latest_version(channel=None)
        request = APIRequestFactory().get('/')
        request.version = 'v5'
        request.user = self.user
        assert data == DeveloperVersionSerializer(
            context={'request': request}
        ).to_representation(version)
        assert version.channel == amo.CHANNEL_UNLISTED
        self.statsd_incr_mock.assert_any_call('addons.submission.version.unlisted')
        self.statsd_incr_mock.assert_any_call('addons.submission.webext_version.12_34')
        provenance = VersionProvenance.objects.get()
        assert provenance.version == version
        assert provenance.source == amo.UPLOAD_SOURCE_ADDON_API
        assert provenance.client_info == 'web-ext/12.34'

    @mock.patch('olympia.addons.views.log')
    def test_does_not_log_without_source(self, log_mock):
        response = self.client.post(
            self.url,
            data=self.minimal_data,
        )
        assert response.status_code == 201, response.content
        assert log_mock.info.call_count == 0

    def test_basic(self):
        self.upload.update(channel=amo.CHANNEL_LISTED)
        self.addon.current_version.file.update(status=amo.STATUS_DISABLED)
        self.addon.update_status()
        assert self.addon.status == amo.STATUS_NULL
        response = self.client.post(
            self.url,
            data={**self.minimal_data, 'license': self.license.slug},
            HTTP_USER_AGENT='web-ext/12.34',
        )
        assert response.status_code == 201, response.content
        data = response.data
        assert data['license'] == LicenseSerializer().to_representation(self.license)
        self.addon.reload()
        assert self.addon.versions.count() == 2
        version = self.addon.find_latest_version(channel=None)
        request = APIRequestFactory().get('/')
        request.version = 'v5'
        request.user = self.user
        assert data == DeveloperVersionSerializer(
            context={'request': request}
        ).to_representation(version)
        assert version.channel == amo.CHANNEL_LISTED
        assert self.addon.status == amo.STATUS_NOMINATED
        self.statsd_incr_mock.assert_any_call('addons.submission.version.listed')
        self.statsd_incr_mock.assert_any_call('addons.submission.webext_version.12_34')
        provenance = VersionProvenance.objects.get()
        assert provenance.version == version
        assert provenance.source == amo.UPLOAD_SOURCE_ADDON_API
        assert provenance.client_info == 'web-ext/12.34'

    def test_not_authenticated(self):
        self.client.logout_api()
        response = self.client.post(
            self.url,
            data=self.minimal_data,
        )
        assert response.status_code == 401
        assert response.data == {
            'detail': 'Authentication credentials were not provided.',
            'is_disabled_by_developer': False,
            'is_disabled_by_mozilla': False,
        }
        assert self.addon.reload().versions.count() == 1

    def test_not_your_addon(self):
        self.addon.addonuser_set.get(user=self.user).update(
            role=amo.AUTHOR_ROLE_DELETED
        )
        response = self.client.post(
            self.url,
            data=self.minimal_data,
        )
        assert response.status_code == 403
        assert response.data['detail'] == (
            'You do not have permission to perform this action.'
        )
        assert self.addon.reload().versions.count() == 1

    def test_not_read_agreement(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.post(
            self.url,
            data=self.minimal_data,
        )
        assert response.status_code in [401, 403]  # JWT auth is a 401; web auth is 403
        assert 'agreement' in response.data['detail'].lower()
        assert self.addon.reload().versions.count() == 1

    def test_waffle_flag_disabled(self):
        gates = {
            'v5': (
                gate
                for gate in settings.DRF_API_GATES['v5']
                if gate != 'addon-submission-api'
            )
        }
        with override_settings(DRF_API_GATES=gates):
            response = self.client.post(
                self.url,
                data=self.minimal_data,
            )
        assert response.status_code == 403
        assert response.data == {
            'detail': 'You do not have permission to perform this action.',
            'is_disabled_by_developer': False,
            'is_disabled_by_mozilla': False,
        }
        assert self.addon.reload().versions.count() == 1

    def test_listed_metadata_missing(self):
        self.addon.current_version.update(license=None)
        self.addon.set_categories([])
        self.upload.update(channel=amo.CHANNEL_LISTED)
        response = self.client.post(
            self.url,
            data={'upload': self.upload.uuid},
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'license': [
                'This field, or custom_license, is required for listed versions.'
            ],
        }

        # If the license is set we'll get further validation errors from about the addon
        # fields that aren't set.
        response = self.client.post(
            self.url,
            data={'upload': self.upload.uuid, 'license': self.license.slug},
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'non_field_errors': [
                'Add-on metadata is required to be set to create a listed version: '
                "['categories']."
            ],
        }

        assert self.addon.reload().versions.count() == 1

    def test_license_inherited_from_previous_version(self):
        previous_license = self.addon.current_version.license
        self.upload.update(channel=amo.CHANNEL_LISTED)
        response = self.client.post(
            self.url,
            data={'upload': self.upload.uuid},
        )
        assert response.status_code == 201, response.content
        self.addon.reload()
        assert self.addon.versions.count() == 2
        version = self.addon.find_latest_version(channel=None)
        assert version.license == previous_license
        self.statsd_incr_mock.assert_any_call('addons.submission.version.listed')

    def test_set_extra_data(self):
        response = self.client.post(
            self.url,
            data={
                **self.minimal_data,
                'release_notes': {'en-US': 'dsdsdsd'},
                'approval_notes': 'This!',
            },
        )

        assert response.status_code == 201, response.content
        data = response.data
        self.addon.reload()
        assert self.addon.versions.count() == 2
        version = self.addon.find_latest_version(channel=None)
        assert data['release_notes'] == {'en-US': 'dsdsdsd'}
        assert version.release_notes == 'dsdsdsd'
        assert version.approval_notes == 'This!'
        self.statsd_incr_mock.assert_any_call('addons.submission.version.unlisted')

    def test_cant_update_disabled_addon(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        response = self.client.post(
            self.url,
            data=self.minimal_data,
        )
        assert response.status_code == 403
        assert response.data['detail'] == (
            'You do not have permission to perform this action.'
        )

    def test_custom_license(self):
        self.upload.update(channel=amo.CHANNEL_LISTED)
        self.addon.current_version.file.update(status=amo.STATUS_DISABLED)
        self.addon.update_status()
        assert self.addon.status == amo.STATUS_NULL
        license_data = {
            'name': {'en-US': 'my custom license name'},
            'text': {'en-US': 'my custom license text'},
        }
        response = self.client.post(
            self.url,
            data={**self.minimal_data, 'custom_license': license_data},
        )
        assert response.status_code == 201, response.content
        data = response.data

        self.addon.reload()
        assert self.addon.versions.count() == 2
        version = self.addon.find_latest_version(channel=None)
        assert version.channel == amo.CHANNEL_LISTED
        assert self.addon.status == amo.STATUS_NOMINATED

        new_license = License.objects.latest('created')
        assert version.license == new_license

        assert data['license'] == {
            'id': new_license.id,
            'name': license_data['name'],
            'text': license_data['text'],
            'is_custom': True,
            'url': 'http://testserver'
            + reverse('addons.license', args=[self.addon.slug]),
            'slug': None,
        }

    def test_cannot_supply_both_custom_and_license_id(self):
        license_data = {
            'name': {'en-US': 'custom license name'},
            'text': {'en-US': 'custom license text'},
        }
        response = self.client.post(
            self.url,
            data={
                **self.minimal_data,
                'license': self.license.slug,
                'custom_license': license_data,
            },
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'non_field_errors': [
                'Both `license` and `custom_license` cannot be provided together.'
            ]
        }

    def test_cannot_submit_listed_to_disabled_(self):
        self.addon.update(disabled_by_user=True)
        self.upload.update(channel=amo.CHANNEL_LISTED)
        response = self.client.post(
            self.url,
            data=self.minimal_data,
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'non_field_errors': [
                'Listed versions cannot be submitted while add-on is disabled.'
            ],
        }

        # but we can submit an unlisted version though
        self.upload.update(channel=amo.CHANNEL_UNLISTED)
        response = self.client.post(
            self.url,
            data=self.minimal_data,
        )
        assert response.status_code == 201, response.content

    def test_duplicate_version_number_error(self):
        self.addon.current_version.update(version='0.0.1')
        response = self.client.post(
            self.url,
            data=self.minimal_data,
        )
        assert response.status_code == 409, response.content
        assert response.json() == {
            'version': ['Version 0.0.1 already exists.'],
        }

        # Still an error if the existing version is disabled
        self.addon.current_version.file.update(status=amo.STATUS_DISABLED)
        response = self.client.post(
            self.url,
            data=self.minimal_data,
        )
        assert response.status_code == 409, response.content
        assert response.json() == {
            'version': ['Version 0.0.1 already exists.'],
        }

        # And even if it's been deleted (different message though)
        self.addon.current_version.delete()
        response = self.client.post(
            self.url,
            data=self.minimal_data,
        )
        assert response.status_code == 409, response.content
        assert response.json() == {
            'version': ['Version 0.0.1 was uploaded before and deleted.'],
        }

    def test_greater_version_number_error(self):
        self.addon.current_version.update(version='0.0.2')
        self.addon.current_version.file.update(is_signed=True)
        self.upload.update(channel=amo.CHANNEL_LISTED)
        response = self.client.post(
            self.url,
            data=self.minimal_data,
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'version': [
                'Version 0.0.1 must be greater than the previous approved version '
                '0.0.2.'
            ],
        }

        # And check for the "same" version number
        self.addon.current_version.update(version='0.0.1.0')
        response = self.client.post(
            self.url,
            data=self.minimal_data,
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'version': [
                'Version 0.0.1 must be greater than the previous approved version '
                '0.0.1.0.'
            ],
        }

    def test_compatibility_gecko_android_in_manifest(self):
        # Only specifying firefox compatibility for an add-on that has explicit
        # gecko_android compatibility in manifest is accepted, but we
        # automatically add Android compatibility.
        self.upload = self.get_upload(
            'webextension_gecko_android.xpi',
            user=self.user,
            source=amo.UPLOAD_SOURCE_ADDON_API,
            channel=amo.CHANNEL_LISTED,
        )
        self.minimal_data = {'upload': self.upload.uuid}
        response = self.request(compatibility={'firefox': {'min': '61.0'}})
        assert response.status_code == self.SUCCESS_STATUS_CODE, response.content
        data = response.data
        assert data['compatibility'] == {
            'android': {
                'max': '*',
                'min': amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY,
            },
            'firefox': {'max': '*', 'min': '61.0'},
        }

    def test_compatibility_with_appversion_locked_from_manifest(self):
        self.upload = self.get_upload(
            'webextension_gecko_android.xpi',
            user=self.user,
            source=amo.UPLOAD_SOURCE_ADDON_API,
            channel=amo.CHANNEL_LISTED,
        )
        self.minimal_data = {'upload': self.upload.uuid}
        response = self.request(
            compatibility={
                'android': {'min': self.APPVERSION_HIGHER_THAN_EVERYTHING_ELSE}
            }
        )
        assert response.status_code == 400
        assert response.data == {
            'compatibility': [
                'Can not override compatibility information set in the manifest for '
                'this application (Firefox for Android)'
            ]
        }

    def _submit_source(self, filepath, error=False):
        _, filename = os.path.split(filepath)
        src = SimpleUploadedFile(
            filename,
            open(filepath, 'rb').read(),
            content_type=mimetypes.guess_type(filename)[0],
        )
        response = self.client.post(
            self.url, data={**self.minimal_data, 'source': src}, format='multipart'
        )
        if not error:
            assert response.status_code == 201, response.content
            self.addon.reload()
            version = self.addon.find_latest_version(channel=None)
        else:
            assert response.status_code == 400
            version = None
        return response, version


class TestVersionViewSetCreateJWTAuth(TestVersionViewSetCreate):
    client_class = APITestClientJWT


class TestVersionViewSetUpdate(UploadMixin, VersionViewSetCreateUpdateMixin, TestCase):
    client_class = APITestClientSessionID
    client_request_verb = 'patch'
    APPVERSION_HIGHER_THAN_EVERYTHING_ELSE = '121.0'

    @classmethod
    def setUpTestData(cls):
        versions = {
            amo.DEFAULT_WEBEXT_MIN_VERSION,
            amo.DEFAULT_WEBEXT_MIN_VERSION_NO_ID,
            amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID,
            amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX,
            amo.DEFAULT_WEBEXT_DICT_MIN_VERSION_FIREFOX,
            amo.DEFAULT_WEBEXT_MAX_VERSION,
            amo.DEFAULT_WEBEXT_MIN_VERSION_GECKO_ANDROID,
            amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY,
            cls.APPVERSION_HIGHER_THAN_EVERYTHING_ELSE,
        }
        for version in versions:
            AppVersion.objects.get_or_create(
                application=amo.FIREFOX.id, version=version
            )
            AppVersion.objects.get_or_create(
                application=amo.ANDROID.id, version=version
            )

    def setUp(self):
        super().setUp()
        self.user = user_factory(read_dev_agreement=self.days_ago(0))
        user_factory(pk=settings.TASK_USER_ID)
        self.addon = addon_factory(
            users=(self.user,),
            guid='@webextension-guid',
            version_kw={
                'license_kw': {'builtin': 1},
                'max_app_version': amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX,
            },
        )
        self.version = self.addon.current_version
        self.url = reverse_ns(
            'addon-version-detail',
            kwargs={'addon_pk': self.addon.slug, 'pk': self.version.id},
            api_version='v5',
        )
        self.client.login_api(self.user)
        AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED
        )

    def test_basic(self):
        response = self.client.patch(
            self.url,
            data={
                'release_notes': {'en-US': 'Something new'},
                'approval_notes': 'secret!',
            },
        )
        assert response.status_code == 200, response.content
        data = response.data
        assert data['release_notes'] == {'en-US': 'Something new'}
        assert data['approval_notes'] == 'secret!'
        self.addon.reload()
        self.version.reload()
        assert self.version.release_notes == 'Something new'
        assert self.version.approval_notes == 'secret!'
        assert self.addon.versions.count() == 1
        version = self.addon.find_latest_version(channel=None)
        request = APIRequestFactory().get('/')
        request.version = 'v5'
        request.user = self.user
        assert data == DeveloperVersionSerializer(
            context={'request': request}
        ).to_representation(version)

    def test_approval_notes_and_release_notes_too_long(self):
        response = self.client.patch(
            self.url,
            data={
                'approval_notes': 'ö' * 3001,
                'release_notes': {'en-US': 'î' * 3001},
            },
        )
        assert response.status_code == 400
        assert response.data == {
            'approval_notes': [
                ErrorDetail(
                    string='Ensure this field has no more than 3000 characters.',
                    code='max_length',
                )
            ],
            'release_notes': [
                ErrorDetail(
                    string='Ensure this field has no more than 3000 characters.',
                    code='max_length',
                )
            ],
        }

    @mock.patch('olympia.addons.views.log')
    def test_does_not_log_without_source(self, log_mock):
        response = self.client.patch(
            self.url,
            data={'release_notes': {'en-US': 'Something new'}},
        )
        assert response.status_code == 200, response.content
        assert log_mock.info.call_count == 0

    def test_not_authenticated(self):
        self.client.logout_api()
        response = self.client.patch(
            self.url,
            data={'release_notes': {'en-US': 'Something new'}},
        )
        assert response.status_code == 401
        assert response.data == {
            'detail': 'Authentication credentials were not provided.',
            'is_disabled_by_developer': False,
            'is_disabled_by_mozilla': False,
        }
        assert self.version.release_notes != 'Something new'

    def test_not_your_addon(self):
        self.addon.addonuser_set.get(user=self.user).update(
            role=amo.AUTHOR_ROLE_DELETED
        )
        response = self.client.patch(
            self.url,
            data={'release_notes': {'en-US': 'Something new'}},
        )
        assert response.status_code == 403
        assert response.data['detail'] == (
            'You do not have permission to perform this action.'
        )
        assert self.version.release_notes != 'Something new'

    def test_not_read_agreement(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.patch(
            self.url,
            data={'release_notes': {'en-US': 'Something new'}},
        )
        assert response.status_code in [401, 403]  # JWT auth is a 401; web auth is 403
        assert 'agreement' in response.data['detail'].lower()
        assert self.version.release_notes != 'Something new'

    def test_waffle_flag_disabled(self):
        gates = {
            'v5': (
                gate
                for gate in settings.DRF_API_GATES['v5']
                if gate != 'addon-submission-api'
            )
        }
        with override_settings(DRF_API_GATES=gates):
            response = self.client.patch(
                self.url,
                data={'release_notes': {'en-US': 'Something new'}},
            )
        assert response.status_code == 403
        assert response.data == {
            'detail': 'You do not have permission to perform this action.',
            'is_disabled_by_developer': False,
            'is_disabled_by_mozilla': False,
        }
        assert self.version.release_notes != 'Something new'

    def test_cant_update_upload(self):
        self.version.update(version='123.b4')
        upload = self.get_upload(
            'webextension.xpi', user=self.user, source=amo.UPLOAD_SOURCE_ADDON_API
        )
        with mock.patch('olympia.addons.serializers.parse_addon') as parse_addon_mock:
            response = self.client.patch(
                self.url,
                data={'upload': upload.uuid},
            )
            parse_addon_mock.assert_not_called()

        assert response.status_code == 200, response.content
        self.addon.reload()
        self.version.reload()
        assert self.version.version == '123.b4'

    def test_cant_update_disabled_addon(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        response = self.client.patch(
            self.url,
            data={'release_notes': {'en-US': 'Something new'}},
        )
        assert response.status_code == 403
        assert response.data['detail'] == (
            'You do not have permission to perform this action.'
        )

    def test_custom_license(self):
        # First assume no license - edge case because we enforce a license for listed
        # versions, but possible.
        self.version.update(license=None)
        license_data = {
            'name': {'en-US': 'custom license name'},
            'text': {'en-US': 'custom license text'},
        }
        response = self.client.patch(
            self.url,
            data={'custom_license': license_data},
        )
        assert response.status_code == 200, response.content
        data = response.data

        self.version.reload()
        new_license = License.objects.latest('created')
        assert self.version.license == new_license
        assert data['license'] == {
            'id': new_license.id,
            'name': license_data['name'],
            'text': license_data['text'],
            'is_custom': True,
            'url': 'http://testserver'
            + reverse('addons.license', args=[self.addon.slug]),
            'slug': None,
        }
        alog = ActivityLog.objects.exclude(
            action__in=(
                amo.LOG.LOG_IN.id,
                amo.LOG.LOG_IN_API_TOKEN.id,
                amo.LOG.CHANGE_STATUS.id,
            )
        ).get()
        assert alog.user == self.user
        assert alog.action == amo.LOG.CHANGE_LICENSE.id

        # And then check we can update an existing custom license
        num_licenses = License.objects.count()
        response = self.client.patch(
            self.url,
            data={'custom_license': {'name': {'en-US': 'neú name'}}},
        )
        assert response.status_code == 200, response.content
        data = response.data

        self.version.reload()
        new_license.reload()
        assert self.version.license == new_license
        assert data['license'] == {
            'id': new_license.id,
            'name': {'en-US': 'neú name'},
            'text': license_data['text'],  # no change
            'is_custom': True,
            'url': 'http://testserver'
            + reverse('addons.license', args=[self.addon.slug]),
            'slug': None,
        }
        assert new_license.name == 'neú name'
        assert License.objects.count() == num_licenses

        alog2 = (
            ActivityLog.objects.exclude(id=alog.id)
            .exclude(
                action__in=(
                    amo.LOG.LOG_IN.id,
                    amo.LOG.LOG_IN_API_TOKEN.id,
                    amo.LOG.CHANGE_STATUS.id,
                )
            )
            .get()
        )
        assert alog2.user == self.user
        assert alog2.action == amo.LOG.CHANGE_LICENSE.id

    def test_custom_license_name_and_text_too_long(self):
        license_data = {
            'name': {'en-US': 'ŋ' * 201},
            'text': {'en-US': 'ŧ' * 75001},
        }
        response = self.client.patch(
            self.url,
            data={'custom_license': license_data},
        )
        assert response.status_code == 400
        assert response.data == {
            'custom_license': {
                'name': [
                    ErrorDetail(
                        string='Ensure this field has no more than 200 characters.',
                        code='max_length',
                    )
                ],
                'text': [
                    ErrorDetail(
                        string='Ensure this field has no more than 75000 characters.',
                        code='max_length',
                    )
                ],
            }
        }

    def test_custom_license_from_builtin(self):
        assert self.version.license.builtin != License.OTHER
        builtin_license = self.version.license
        license_data = {
            'name': {'en-US': 'custom license name'},
            'text': {'en-US': 'custom license text'},
        }
        response = self.client.patch(
            self.url,
            data={'custom_license': license_data},
        )
        assert response.status_code == 200, response.content
        data = response.data

        self.version.reload()
        new_license = License.objects.latest('created')
        assert self.version.license == new_license
        assert new_license != builtin_license
        assert data['license'] == {
            'id': new_license.id,
            'name': license_data['name'],
            'text': license_data['text'],
            'is_custom': True,
            'url': 'http://testserver'
            + reverse('addons.license', args=[self.addon.slug]),
            'slug': None,
        }
        alog = ActivityLog.objects.exclude(
            action__in=(
                amo.LOG.LOG_IN.id,
                amo.LOG.LOG_IN_API_TOKEN.id,
                amo.LOG.CHANGE_STATUS.id,
            )
        ).get()
        assert alog.user == self.user
        assert alog.action == amo.LOG.CHANGE_LICENSE.id

        # and check we can change back to a builtin from a custom license
        response = self.client.patch(
            self.url,
            data={'license': builtin_license.slug},
        )
        assert response.status_code == 200, response.content
        data = response.data

        self.version.reload()
        assert self.version.license == builtin_license
        assert data['license']['id'] == builtin_license.id
        assert data['license']['name']['en-US'] == str(builtin_license)
        assert data['license']['is_custom'] is False
        assert data['license']['url'] == builtin_license.url
        alog2 = (
            ActivityLog.objects.exclude(id=alog.id)
            .exclude(
                action__in=(
                    amo.LOG.LOG_IN.id,
                    amo.LOG.LOG_IN_API_TOKEN.id,
                    amo.LOG.CHANGE_STATUS.id,
                )
            )
            .get()
        )
        assert alog2.user == self.user
        assert alog2.action == amo.LOG.CHANGE_LICENSE.id

    def test_no_custom_license_for_themes(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        license_data = {
            'name': {'en-US': 'custom license name'},
            'text': {'en-US': 'custom license text'},
        }
        response = self.client.patch(
            self.url,
            data={'custom_license': license_data},
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'custom_license': ['Custom licenses are not supported for themes.']
        }

    def test_license_type_matches_addon_type(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.patch(
            self.url,
            data={'license': self.version.license.slug},
        )
        assert response.status_code == 400, response.content
        assert response.data == {'license': ['Wrong add-on type for this license.']}

        self.addon.update(type=amo.ADDON_EXTENSION)
        self.version.license.update(builtin=12)
        response = self.client.patch(
            self.url,
            data={'license': self.version.license.slug},
        )
        assert response.status_code == 400, response.content
        assert response.data == {'license': ['Wrong add-on type for this license.']}

    def test_cannot_supply_both_custom_and_license_id(self):
        license_data = {
            'name': {'en-US': 'custom license name'},
            'text': {'en-US': 'custom license text'},
        }
        response = self.client.patch(
            self.url,
            data={'license': self.version.license.slug, 'custom_license': license_data},
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'non_field_errors': [
                'Both `license` and `custom_license` cannot be provided together.'
            ]
        }

    @mock.patch('olympia.addons.views.log')
    def _test_delete_source(self, request_kw, log_mock):
        self.version.update(source='src.zip')
        response = self.client.patch(self.url, **request_kw)
        assert response.status_code == 200, response.content
        self.version.reload()
        assert not self.version.source
        # No logging when setting source to None.
        assert log_mock.info.call_count == 0

    def test_delete_source_json(self):
        self._test_delete_source({'data': {'source': None}})

    def test_delete_source_formdata(self):
        self._test_delete_source({'data': {'source': ''}, 'format': 'multipart'})

    def _submit_source(self, filepath, error=False):
        _, filename = os.path.split(filepath)
        src = SimpleUploadedFile(
            filename,
            open(filepath, 'rb').read(),
            content_type=mimetypes.guess_type(filename)[0],
        )
        response = self.client.patch(self.url, data={'source': src}, format='multipart')
        if not error:
            assert response.status_code == 200, response.content
        else:
            assert response.status_code == 400
        self.version.reload()
        return response, self.version

    def test_cant_delete_source_for_reviewed_file(self):
        mock_point = 'olympia.versions.models.Version.'
        error = {
            'source': [
                'Source cannot be changed because this version has been reviewed by '
                'Mozilla.'
            ]
        }
        self.version.update(source='src.zip', human_review_date=datetime.now())

        with mock.patch(
            f'{mock_point}pending_rejection', new_callable=mock.PropertyMock
        ) as pending_mock:
            pending_mock.return_value = False

            response = self.client.patch(self.url, data={'source': None})
            assert response.status_code == 400, response.content
            assert response.data == error
            self.version.reload()
            assert self.version.source

            response = self.client.patch(
                self.url, data={'source': ''}, format='multipart'
            )
            assert response.status_code == 400, response.content
            assert response.data == error
            self.version.reload()
            assert self.version.source

            pending_mock.return_value = True
            response = self.client.patch(self.url, data={'source': None})
            assert response.status_code == 200, response.content
            assert response.data != error
            self.version.reload()
            assert not self.version.source

    def test_cant_upload_source_for_reviewed_file(self):
        mock_point = 'olympia.versions.models.Version.'
        error = {
            'source': [
                'Source cannot be changed because this version has been reviewed by '
                'Mozilla.'
            ]
        }
        new_source = self.file_path('webextension_with_image.zip')

        assert not self.version.source
        with mock.patch(
            f'{mock_point}pending_rejection', new_callable=mock.PropertyMock
        ) as pending_mock:
            self.version.update(human_review_date=datetime.now())
            pending_mock.return_value = False
            assert self._submit_source(new_source, error=True)[0].data == error
            assert not self.version.source

            pending_mock.return_value = True
            assert self._submit_source(new_source, error=False)[0].data != error
            assert self.version.source

    def test_submit_source_pending_rejection_triggers_needs_human_review(self):
        assert not self.version.source
        new_source = self.file_path('webextension_with_image.zip')
        VersionReviewerFlags.objects.create(
            version=self.version,
            pending_rejection=datetime.now() + timedelta(days=2),
            pending_rejection_by=user_factory(),
            pending_content_rejection=False,
        )
        response, self.version = self._submit_source(new_source)
        self.addon.reload()
        assert self.version.source
        assert self.version.needshumanreview_set.filter(is_active=True).exists()
        log = ActivityLog.objects.get(action=amo.LOG.SOURCE_CODE_UPLOADED.id)
        assert log.user == self.user
        assert log.details is None
        assert log.arguments == [self.addon, self.version]

    def test_disable_enabled_version(self):
        # first test the case where the file is disabled by rejection or obsolescence
        self.version.file.update(status=amo.STATUS_DISABLED)
        assert not self.version.is_user_disabled
        response = self.client.patch(self.url, data={'is_disabled': True})
        assert response.status_code == 400, response.content
        assert response.data == {'is_disabled': ['File is already disabled.']}

        # But if the file isn't disabled the version should be good to disable
        self.version.file.update(status=amo.STATUS_APPROVED)
        response = self.client.patch(self.url, data={'is_disabled': True})

        assert response.status_code == 200, response.content
        assert response.data['is_disabled'] is True
        self.version.reload()
        self.version.file.reload()
        assert self.version.is_user_disabled
        assert self.version.file.status == amo.STATUS_DISABLED
        alog = ActivityLog.objects.exclude(
            action__in=(
                amo.LOG.LOG_IN.id,
                amo.LOG.LOG_IN_API_TOKEN.id,
                amo.LOG.CHANGE_STATUS.id,
            )
        ).get()
        assert alog.user == self.user
        assert alog.action == amo.LOG.DISABLE_VERSION.id

    def test_cannot_disable_if_promoted(self):
        self.make_addon_promoted(self.addon, RECOMMENDED, approve_version=True)

        response = self.client.patch(self.url, data={'is_disabled': True})
        assert response.status_code == 400
        assert response.json()['is_disabled'][0].startswith(
            'The latest approved version of this Recommended add-on cannot be deleted'
        )
        assert len(response.json()) == 1
        assert not self.version.reload().is_user_disabled

        # Now add another version so it's okay to disable one of them
        self.version = version_factory(addon=self.addon, promotion_approved=True)
        self.addon.reload()
        self.url = reverse_ns(
            'addon-version-detail',
            kwargs={'addon_pk': self.addon.slug, 'pk': self.version.id},
            api_version='v5',
        )
        response = self.client.patch(self.url, data={'is_disabled': True})
        assert response.status_code == 200
        self.version.reload()
        self.version.file.reload()
        assert self.version.is_user_disabled
        assert self.version.file.status == amo.STATUS_DISABLED
        alog = ActivityLog.objects.exclude(
            action__in=(
                amo.LOG.LOG_IN.id,
                amo.LOG.LOG_IN_API_TOKEN.id,
                amo.LOG.CHANGE_STATUS.id,
            )
        ).get()
        assert alog.user == self.user
        assert alog.action == amo.LOG.DISABLE_VERSION.id

    def test_enable_disabled_version(self):
        self.version.is_user_disabled = True
        response = self.client.patch(self.url, data={'is_disabled': False})
        assert response.status_code == 200, response.content
        assert response.data['is_disabled'] is False
        self.version.reload()
        self.version.file.reload()
        assert not self.version.is_user_disabled
        alog = ActivityLog.objects.exclude(
            action__in=(
                amo.LOG.LOG_IN.id,
                amo.LOG.LOG_IN_API_TOKEN.id,
                amo.LOG.CHANGE_STATUS.id,
            )
        ).get()
        assert alog.user == self.user
        assert alog.action == amo.LOG.ENABLE_VERSION.id

    def test_compatibility_with_appversion_locked_from_manifest(self):
        # Add a 114.0 for Android coming from manifest. It shouldn't be
        # possible for the developer to remove it in any way.
        self.version.apps.create(
            application=amo.ANDROID.id,
            min=AppVersion.objects.get(
                application=amo.ANDROID.id,
                version=self.APPVERSION_HIGHER_THAN_EVERYTHING_ELSE,
            ),
            max=AppVersion.objects.get(
                application=amo.ANDROID.id,
                version=amo.DEFAULT_WEBEXT_MAX_VERSION,
            ),
            originated_from=amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST_GECKO_ANDROID,
        )
        response = self.request(compatibility=['firefox'])
        assert response.status_code == 400, response.content
        assert response.data['compatibility'] == [
            'Can not override compatibility information set in the manifest for this '
            'application (Firefox for Android)'
        ]

        response = self.request(
            compatibility={
                'firefox': {'min': amo.DEFAULT_WEBEXT_MIN_VERSION_MV3_FIREFOX}
            }
        )
        assert response.status_code == 400, response.content
        assert response.data['compatibility'] == [
            'Can not override compatibility information set in the manifest for this '
            'application (Firefox for Android)'
        ]

        response = self.request(
            compatibility={
                'firefox': {'min': amo.DEFAULT_WEBEXT_MIN_VERSION},
                'android': {'min': amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY},
            }
        )
        assert response.status_code == 400, response.content
        assert response.data['compatibility'] == [
            'Can not override compatibility information set in the manifest for this '
            'application (Firefox for Android)'
        ]


class TestVersionViewSetUpdateJWTAuth(TestVersionViewSetUpdate):
    client_class = APITestClientJWT


class TestVersionViewSetDelete(TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        super().setUp()
        self.user = user_factory(read_dev_agreement=self.days_ago(0))
        self.addon = addon_factory(users=(self.user,))
        self.version = self.addon.current_version
        self.url = reverse_ns(
            'addon-version-detail',
            kwargs={'addon_pk': self.addon.slug, 'pk': self.version.id},
            api_version='v5',
        )

    def test_delete(self):
        assert not self.version.deleted

        response = self.client.delete(self.url)
        assert response.status_code == 401
        assert not self.version.reload().deleted

        self.client.login_api(self.user)
        response = self.client.delete(self.url)
        assert response.status_code == 204
        assert self.version.reload().deleted
        assert self.addon.reload().status == amo.STATUS_NULL

    def test_not_author_cannot_delete(self):
        another_user = user_factory(read_dev_agreement=self.days_ago(0))
        self.client.login_api(another_user)
        response = self.client.delete(self.url)
        assert response.status_code == 403
        assert not self.version.reload().deleted

        # even if they are a reviewer
        self.grant_permission(another_user, ':'.join(amo.permissions.ADDONS_REVIEW))
        response = self.client.delete(self.url)
        assert response.status_code == 403
        assert not self.version.reload().deleted

        # or have admin-ish permissions
        self.grant_permission(another_user, ':'.join(amo.permissions.ADDONS_EDIT))
        response = self.client.delete(self.url)
        assert response.status_code == 403
        assert not self.version.reload().deleted

    def test_author_developer_can_delete(self):
        self.addon.addonuser_set.all()[0].update(role=amo.AUTHOR_ROLE_DEV)
        self.client.login_api(self.user)
        response = self.client.delete(self.url)
        assert response.status_code == 204
        assert self.version.reload().deleted

    def test_cannot_delete_if_promoted(self):
        self.make_addon_promoted(self.addon, RECOMMENDED, approve_version=True)
        self.client.login_api(self.user)

        response = self.client.delete(self.url)
        assert response.status_code == 400
        assert response.json()[0].startswith(
            'The latest approved version of this Recommended add-on cannot be deleted'
        )
        assert len(response.json()) == 1
        assert not self.version.reload().deleted

        # Now add another version so it's okay to delete one of them
        self.version = version_factory(addon=self.addon, promotion_approved=True)
        self.addon.reload()
        self.url = reverse_ns(
            'addon-version-detail',
            kwargs={'addon_pk': self.addon.slug, 'pk': self.version.id},
            api_version='v5',
        )

        response = self.client.delete(self.url)
        assert response.status_code == 204
        assert self.version.reload().deleted
        assert self.addon.reload().status == amo.STATUS_APPROVED


class TestVersionViewSetDeleteJWTAuth(TestVersionViewSetDelete):
    client_class = APITestClientJWT


class TestVersionViewSetList(AddonAndVersionViewSetDetailMixin, TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        super().setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(), name='My Addôn', slug='my-addon'
        )
        self.old_version = self.addon.current_version
        self.old_version.update(created=self.days_ago(2))

        # Don't use addon.current_version, changing its state as we do in
        # the tests might render the add-on itself inaccessible.
        self.version = version_factory(addon=self.addon, version='1.0.1')
        self.version.update(created=self.days_ago(1))

        # This version is unlisted and should be hidden by default, only
        # shown when requesting to see unlisted stuff explicitly, with the
        # right permissions.
        self.unlisted_version = version_factory(
            addon=self.addon, version='42.0', channel=amo.CHANNEL_UNLISTED
        )

        self._set_tested_url(self.addon.pk)

    def _test_url(self, **kwargs):
        response = self.client.get(self.url, data=kwargs)
        assert response.status_code == 200
        result = json.loads(force_str(response.content))
        assert result['results']
        assert len(result['results']) == 2
        result_version = result['results'][0]
        assert result_version['id'] == self.version.pk
        assert result_version['version'] == self.version.version
        assert result_version['license']
        assert 'text' not in result_version['license']
        result_version = result['results'][1]
        assert result_version['id'] == self.old_version.pk
        assert result_version['version'] == self.old_version.version
        assert result_version['license']
        assert 'text' not in result_version['license']

    def _test_url_contains_all(self, **kwargs):
        response = self.client.get(self.url, data=kwargs)
        assert response.status_code == 200
        result = json.loads(force_str(response.content))
        assert result['results']
        assert len(result['results']) == 3
        result_version = result['results'][0]
        assert result_version['id'] == self.unlisted_version.pk
        assert result_version['version'] == self.unlisted_version.version
        result_version = result['results'][1]
        assert result_version['id'] == self.version.pk
        assert result_version['version'] == self.version.version
        result_version = result['results'][2]
        assert result_version['id'] == self.old_version.pk
        assert result_version['version'] == self.old_version.version

    def _test_url_only_contains_old_version(self, **kwargs):
        response = self.client.get(self.url, data=kwargs)
        assert response.status_code == 200
        result = json.loads(force_str(response.content))
        assert result['results']
        assert len(result['results']) == 1
        result_version = result['results'][0]
        assert result_version['id'] == self.old_version.pk
        assert result_version['version'] == self.old_version.version

    def _set_tested_url(self, param):
        self.url = reverse_ns('addon-version-list', kwargs={'addon_pk': param})

    def test_queries(self):
        with self.assertNumQueries(10):
            # 11 queries:
            # - 2 savepoints because of tests
            # - 2 addon and its translations
            # - 1 count for pagination
            # - 1 versions themselves, their files and webext permissions
            # - 1 translations (release notes)
            # - 1 applications versions
            # - 1 licenses
            # - 1 licenses translations
            self._test_url(lang='en-US')

    def test_old_api_versions_have_license_text(self):
        current_api_version = settings.REST_FRAMEWORK['DEFAULT_VERSION']
        old_api_versions = ('v3', 'v4')
        assert (
            'keep-license-text-in-version-list'
            not in settings.DRF_API_GATES[current_api_version]
        )
        for api_version in old_api_versions:
            assert (
                'keep-license-text-in-version-list'
                in settings.DRF_API_GATES[api_version]
            )

        overridden_api_gates = {
            current_api_version: ('keep-license-text-in-version-list',)
        }
        with override_settings(DRF_API_GATES=overridden_api_gates):
            response = self.client.get(self.url)
            assert response.status_code == 200
            result = json.loads(force_str(response.content))
            assert result['results']
            assert len(result['results']) == 2
            result_version = result['results'][0]
            assert result_version['id'] == self.version.pk
            assert result_version['version'] == self.version.version
            assert result_version['license']
            assert result_version['license']['text']
            result_version = result['results'][1]
            assert result_version['id'] == self.old_version.pk
            assert result_version['version'] == self.old_version.version
            assert result_version['license']
            assert result_version['license']['text']

    def test_bad_filter(self):
        response = self.client.get(self.url, data={'filter': 'ahahaha'})
        assert response.status_code == 400
        data = json.loads(force_str(response.content))
        assert data == ['Invalid "filter" parameter specified.']

    def test_disabled_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.file.update(status=amo.STATUS_DISABLED)
        self._test_url_only_contains_old_version()

        # A reviewer can see disabled versions when explicitly asking for them.
        self._test_url(filter='all_without_unlisted')

    def test_disabled_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        self.version.file.update(status=amo.STATUS_DISABLED)
        self._test_url_only_contains_old_version()

        # An author can see disabled versions when explicitly asking for them.
        self._test_url(filter='all_without_unlisted')

    def test_disabled_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self.version.file.update(status=amo.STATUS_DISABLED)
        self._test_url_only_contains_old_version()

        # An admin can see disabled versions when explicitly asking for them.
        self._test_url(filter='all_without_unlisted')

    def test_disabled_version_anonymous(self):
        self.version.file.update(status=amo.STATUS_DISABLED)
        self._test_url_only_contains_old_version()
        response = self.client.get(self.url, data={'filter': 'all_without_unlisted'})
        assert response.status_code == 401
        response = self.client.get(self.url, data={'filter': 'all_with_deleted'})
        assert response.status_code == 401

    def test_disabled_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.file.update(status=amo.STATUS_DISABLED)
        self._test_url_only_contains_old_version()
        response = self.client.get(self.url, data={'filter': 'all_without_unlisted'})
        assert response.status_code == 403
        response = self.client.get(self.url, data={'filter': 'all_with_deleted'})
        assert response.status_code == 403

    def test_deleted_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.delete()
        self._test_url_only_contains_old_version()
        self._test_url_only_contains_old_version(filter='all_without_unlisted')
        response = self.client.get(self.url, data={'filter': 'all_with_deleted'})
        assert response.status_code == 403
        response = self.client.get(self.url, data={'filter': 'all_with_unlisted'})
        assert response.status_code == 403

    def test_deleted_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        self.version.delete()
        self._test_url_only_contains_old_version()
        self._test_url_only_contains_old_version(filter='all_without_unlisted')
        response = self.client.get(self.url, data={'filter': 'all_with_deleted'})
        assert response.status_code == 403

    def test_deleted_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self.version.delete()
        self._test_url_only_contains_old_version()
        self._test_url_only_contains_old_version(filter='all_without_unlisted')

        # An admin can see deleted versions when explicitly asking
        # for them.
        self._test_url_contains_all(filter='all_with_deleted')

    def test_all_with_unlisted_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self._test_url_contains_all(filter='all_with_unlisted')

    def test_with_unlisted_unlisted_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.client.login_api(user)

    def test_with_unlisted_unlisted_viewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'ReviewerTools:ViewUnlisted')
        self.client.login_api(user)

        self._test_url_contains_all(filter='all_with_unlisted')

    def test_with_unlisted_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)

        self._test_url_contains_all(filter='all_with_unlisted')

    def test_all_with_unlisted_when_no_unlisted_versions(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.client.login_api(user)
        # delete the unlisted version so only the listed versions remain.
        self.unlisted_version.delete()

        # confirm that we have access to view unlisted versions.
        response = self.client.get(self.url, data={'filter': 'all_with_unlisted'})
        assert response.status_code == 200
        result = json.loads(force_str(response.content))
        assert result['results']
        assert len(result['results']) == 2
        result_version = result['results'][0]
        assert result_version['id'] == self.version.pk
        assert result_version['version'] == self.version.version

        # And that without_unlisted doesn't fail when there are no unlisted
        response = self.client.get(self.url, data={'filter': 'all_without_unlisted'})
        assert response.status_code == 200

    def test_all_with_unlisted_when_no_unlisted_versions_viewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'ReviewerTools:ViewUnlisted')
        self.client.login_api(user)
        # delete the unlisted version so only the listed versions remain.
        self.unlisted_version.delete()

        # confirm that we have access to view unlisted versions.
        response = self.client.get(self.url, data={'filter': 'all_with_unlisted'})
        assert response.status_code == 200
        result = json.loads(force_str(response.content))
        assert result['results']
        assert len(result['results']) == 2
        result_version = result['results'][0]
        assert result_version['id'] == self.version.pk
        assert result_version['version'] == self.version.version

        # And that without_unlisted doesn't fail when there are no unlisted
        response = self.client.get(self.url, data={'filter': 'all_without_unlisted'})
        assert response.status_code == 200

    def test_deleted_version_anonymous(self):
        self.version.delete()
        self._test_url_only_contains_old_version()

        response = self.client.get(self.url, data={'filter': 'all_with_deleted'})
        assert response.status_code == 401

    def test_all_without_and_with_unlisted_anonymous(self):
        response = self.client.get(self.url, data={'filter': 'all_without_unlisted'})
        assert response.status_code == 401
        response = self.client.get(self.url, data={'filter': 'all_with_unlisted'})
        assert response.status_code == 401

    def test_deleted_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.delete()
        self._test_url_only_contains_old_version()

        response = self.client.get(self.url, data={'filter': 'all_with_deleted'})
        assert response.status_code == 403

    def test_all_without_and_with_unlisted_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.delete()
        response = self.client.get(self.url, data={'filter': 'all_without_unlisted'})
        assert response.status_code == 403
        response = self.client.get(self.url, data={'filter': 'all_with_unlisted'})
        assert response.status_code == 403

    def test_all_without_unlisted_when_no_listed_versions(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.client.login_api(user)
        # delete the listed versions so only the unlisted version remains.
        self.version.delete()
        self.old_version.delete()

        # confirm that we have access to view unlisted versions.
        response = self.client.get(self.url, data={'filter': 'all_with_unlisted'})
        assert response.status_code == 200
        result = json.loads(force_str(response.content))
        assert result['results']
        assert len(result['results']) == 1
        result_version = result['results'][0]
        assert result_version['id'] == self.unlisted_version.pk
        assert result_version['version'] == self.unlisted_version.version

        # And that without_unlisted doesn't fail when there are no unlisted
        response = self.client.get(self.url, data={'filter': 'all_without_unlisted'})
        assert response.status_code == 200
        result = json.loads(force_str(response.content))
        assert result['results'] == []

    def test_all_without_unlisted_when_no_listed_versions_for_viewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'ReviewerTools:ViewUnlisted')
        self.client.login_api(user)
        # delete the listed versions so only the unlisted version remains.
        self.version.delete()
        self.old_version.delete()

        # confirm that we have access to view unlisted versions.
        response = self.client.get(self.url, data={'filter': 'all_with_unlisted'})
        assert response.status_code == 200
        result = json.loads(force_str(response.content))
        assert result['results']
        assert len(result['results']) == 1
        result_version = result['results'][0]
        assert result_version['id'] == self.unlisted_version.pk
        assert result_version['version'] == self.unlisted_version.version

        # And that without_unlisted doesn't fail when there are no unlisted
        response = self.client.get(self.url, data={'filter': 'all_without_unlisted'})
        assert response.status_code == 200
        result = json.loads(force_str(response.content))
        assert result['results'] == []

    def test_developer_version_serializer_used_for_authors(self):
        self.version.update(source='src.zip')
        # not logged in
        assert 'source' not in self.client.get(self.url).data['results'][0]
        assert 'source' not in self.client.get(self.url).data['results'][1]

        user = UserProfile.objects.create(username='user')
        self.client.login_api(user)

        # logged in but not an author
        assert 'source' not in self.client.get(self.url).data['results'][0]
        assert 'source' not in self.client.get(self.url).data['results'][1]

        AddonUser.objects.create(user=user, addon=self.addon)

        # the field is present when the user is an author of the add-on.
        assert 'source' in self.client.get(self.url).data['results'][0]
        assert 'source' in self.client.get(self.url).data['results'][1]


class TestAddonViewSetEulaPolicy(TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        super().setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(), name='My Addôn', slug='my-addon'
        )
        self.url = reverse_ns('addon-eula-policy', kwargs={'pk': self.addon.pk})

    def test_url(self):
        self.detail_url = reverse_ns('addon-detail', kwargs={'pk': self.addon.pk})
        assert self.url == '{}{}'.format(self.detail_url, 'eula_policy/')

    def test_disabled_anonymous(self):
        self.addon.update(disabled_by_user=True)
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_policy_none(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['eula'] is None
        assert data['privacy_policy'] is None

    def test_policy(self):
        self.addon.eula = {'en-US': 'My Addôn EULA', 'fr': 'Hoüla'}
        self.addon.privacy_policy = 'My Prïvacy, My Policy'
        self.addon.save()
        response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['eula'] == {'en-US': 'My Addôn EULA', 'fr': 'Hoüla'}
        assert data['privacy_policy'] == {'en-US': 'My Prïvacy, My Policy'}


class TestAddonSearchView(ESTestCase):
    client_class = APITestClientSessionID

    fixtures = ['base/users']

    def setUp(self):
        super().setUp()
        self.url = reverse_ns('addon-search')
        # Create return to AMO waffle switches used for rta: guid search, then
        # fetch them once to get them in the cache.
        self.create_switch('return-to-amo', active=True)
        self.create_switch('return-to-amo-for-all-listed', active=False)
        switch_is_active('return-to-amo')
        switch_is_active('return-to-amo-for-all-listed')

    def tearDown(self):
        super().tearDown()
        self.empty_index('default')
        self.refresh()

    def test_get_queryset_excludes(self):
        addon_factory(slug='my-addon', name='My Addôn', popularity=666)
        addon_factory(slug='my-second-addon', name='My second Addôn', popularity=555)
        self.refresh()

        view = AddonSearchView()
        view.request = APIRequestFactory().get('/')
        qset = view.get_queryset()

        assert set(qset.to_dict()['_source']['excludes']) == {
            '*.raw',
            'boost',
            'colors',
            'hotness',
            'name',
            'description',
            'name_l10n_*',
            'description_l10n_*',
            'summary',
            'summary_l10n_*',
        }

        response = qset.execute()

        source_keys = response.hits.hits[0]['_source'].to_dict().keys()

        assert not any(
            key in source_keys
            for key in (
                'boost',
                'description',
                'hotness',
                'name',
                'summary',
            )
        )

        assert not any(key.startswith('name_l10n_') for key in source_keys)

        assert not any(key.startswith('description_l10n_') for key in source_keys)

        assert not any(key.startswith('summary_l10n_') for key in source_keys)

        assert not any(key.endswith('.raw') for key in source_keys)

    def perform_search(self, url, data=None, expected_status=200, **headers):
        with self.assertNumQueries(0):
            response = self.client.get(url, data, **headers)
        assert response.status_code == expected_status, response.content
        data = json.loads(force_str(response.content))
        return data

    def test_basic(self):
        addon = addon_factory(slug='my-addon', name='My Addôn', popularity=666)
        addon2 = addon_factory(
            slug='my-second-addon', name='My second Addôn', popularity=555
        )
        self.refresh()

        data = self.perform_search(self.url)  # No query.
        assert data['count'] == 2
        assert len(data['results']) == 2

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['name'] == {'en-US': 'My Addôn'}
        assert result['slug'] == 'my-addon'
        assert result['last_updated'] == (
            addon.last_updated.replace(microsecond=0).isoformat() + 'Z'
        )

        # latest_unlisted_version should never be exposed in public search.
        assert 'latest_unlisted_version' not in result

        result = data['results'][1]
        assert result['id'] == addon2.pk
        assert result['name'] == {'en-US': 'My second Addôn'}
        assert result['slug'] == 'my-second-addon'

        # latest_unlisted_version should never be exposed in public search.
        assert 'latest_unlisted_version' not in result

    @mock.patch('django_statsd.middleware.statsd.timing')
    def test_statsd_timings(self, statsd_timing_mock):
        self.perform_search(self.url)
        assert statsd_timing_mock.call_count == 3
        assert (
            statsd_timing_mock.call_args_list[0][0][0]
            == 'view.olympia.addons.views.AddonSearchView.GET'
        )
        assert (
            statsd_timing_mock.call_args_list[1][0][0]
            == 'view.olympia.addons.views.GET'
        )
        assert statsd_timing_mock.call_args_list[2][0][0] == 'view.GET'

    def test_empty(self):
        data = self.perform_search(self.url)
        assert data['count'] == 0
        assert len(data['results']) == 0

    def test_es_queries_made_no_results(self):
        with patch.object(
            Elasticsearch, 'search', wraps=get_es().search
        ) as search_mock:
            data = self.perform_search(self.url, data={'q': 'foo'})
            assert data['count'] == 0
            assert len(data['results']) == 0
            assert search_mock.call_count == 1

    def test_es_queries_made_some_result(self):
        addon_factory(slug='foormidable', name='foo')
        addon_factory(slug='foobar', name='foo')
        self.refresh()

        with patch.object(
            Elasticsearch, 'search', wraps=get_es().search
        ) as search_mock:
            data = self.perform_search(self.url, data={'q': 'foo', 'page_size': 1})
            assert data['count'] == 2
            assert len(data['results']) == 1
            assert search_mock.call_count == 1

    def test_no_unlisted(self):
        addon_factory(
            slug='my-addon',
            name='My Addôn',
            status=amo.STATUS_NULL,
            popularity=666,
            version_kw={'channel': amo.CHANNEL_UNLISTED},
        )
        self.refresh()
        data = self.perform_search(self.url)
        assert data['count'] == 0
        assert len(data['results']) == 0

    def test_pagination(self):
        addon = addon_factory(slug='my-addon', name='My Addôn', popularity=33)
        addon2 = addon_factory(
            slug='my-second-addon', name='My second Addôn', popularity=22
        )
        addon_factory(slug='my-third-addon', name='My third Addôn', popularity=11)
        self.refresh()

        data = self.perform_search(self.url, {'page_size': 1})
        assert data['count'] == 3
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['name'] == {'en-US': 'My Addôn'}
        assert result['slug'] == 'my-addon'

        # Search using the second page URL given in return value.
        data = self.perform_search(data['next'])
        assert data['count'] == 3
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon2.pk
        assert result['name'] == {'en-US': 'My second Addôn'}
        assert result['slug'] == 'my-second-addon'

    def test_pagination_sort_and_query(self):
        addon_factory(slug='my-addon', name='Cy Addôn')
        addon2 = addon_factory(slug='my-second-addon', name='By second Addôn')
        addon1 = addon_factory(slug='my-first-addon', name='Ay first Addôn')
        addon_factory(slug='only-happy-when-itrains', name='Garbage')
        self.refresh()

        data = self.perform_search(
            self.url, {'page_size': 1, 'q': 'addôn', 'sort': 'name'}
        )
        assert data['count'] == 3
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon1.pk
        assert result['name'] == {'en-US': 'Ay first Addôn'}

        # Search using the second page URL given in return value.
        assert 'sort=name' in data['next']
        data = self.perform_search(data['next'])
        assert data['count'] == 3
        assert len(data['results']) == 1
        assert 'sort=name' in data['previous']

        result = data['results'][0]
        assert result['id'] == addon2.pk
        assert result['name'] == {'en-US': 'By second Addôn'}

    def test_filtering_only_reviewed_addons(self):
        public_addon = addon_factory(slug='my-addon', name='My Addôn', popularity=222)
        addon_factory(
            slug='my-incomplete-addon',
            name='My incomplete Addôn',
            status=amo.STATUS_NULL,
        )
        addon_factory(
            slug='my-disabled-addon',
            name='My disabled Addôn',
            status=amo.STATUS_DISABLED,
        )
        addon_factory(
            slug='my-unlisted-addon',
            name='My unlisted Addôn',
            version_kw={'channel': amo.CHANNEL_UNLISTED},
        )
        addon_factory(
            slug='my-disabled-by-user-addon',
            name='My disabled by user Addôn',
            disabled_by_user=True,
        )
        self.refresh()

        data = self.perform_search(self.url)
        assert data['count'] == 1
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == public_addon.pk
        assert result['name'] == {'en-US': 'My Addôn'}
        assert result['slug'] == 'my-addon'

    def test_with_query(self):
        addon = addon_factory(slug='my-addon', name='My Addon', tags=['some_tag'])
        addon_factory(slug='unrelated', name='Unrelated')
        self.refresh()

        data = self.perform_search(self.url, {'q': 'addon'})
        assert data['count'] == 1
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['name'] == {'en-US': 'My Addon'}
        assert result['slug'] == 'my-addon'

    def test_with_session_cookie(self):
        # Session cookie should be ignored, therefore a request with it should
        # not cause more database queries.
        self.client.force_login(UserProfile.objects.get(email='regular@mozilla.com'))
        data = self.perform_search(self.url)
        assert data['count'] == 0
        assert len(data['results']) == 0

    def test_filter_by_type(self):
        addon = addon_factory(slug='my-addon', name='My Addôn')
        theme = addon_factory(
            slug='my-theme', name='My Thème', type=amo.ADDON_STATICTHEME
        )
        addon_factory(slug='my-dict', name='My Dîct', type=amo.ADDON_DICT)
        self.refresh()

        data = self.perform_search(self.url)
        assert data['count'] == 3
        assert len(data['results']) == 3

        data = self.perform_search(self.url, {'type': 'extension'})
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == addon.pk

        data = self.perform_search(self.url, {'type': 'statictheme'})
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == theme.pk

        data = self.perform_search(self.url, {'type': 'statictheme,extension'})
        assert data['count'] == 2
        assert len(data['results']) == 2
        result_ids = (data['results'][0]['id'], data['results'][1]['id'])
        assert sorted(result_ids) == [addon.pk, theme.pk]

    def test_filter_by_featured_no_app_no_lang(self):
        addon = addon_factory(
            slug='my-addon', name='Featured Addôn', promoted=RECOMMENDED
        )
        addon_factory(slug='other-addon', name='Other Addôn')
        assert addon.promoted_group() == RECOMMENDED
        self.reindex(Addon)

        data = self.perform_search(self.url, {'featured': 'true'})
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == addon.pk

    def test_filter_by_promoted(self):
        av_min, _ = AppVersion.objects.get_or_create(
            application=amo.ANDROID.id, version='59.0.0'
        )
        av_max, _ = AppVersion.objects.get_or_create(
            application=amo.ANDROID.id, version='60.0.0'
        )

        addon = addon_factory(name='Recomménded Addôn', promoted=RECOMMENDED)
        ApplicationsVersions.objects.get_or_create(
            application=amo.ANDROID.id,
            version=addon.current_version,
            min=av_min,
            max=av_max,
        )
        assert addon.promoted_group() == RECOMMENDED
        assert addon.promotedaddon.application_id is None  # i.e. all
        assert addon.promotedaddon.approved_applications == [amo.FIREFOX, amo.ANDROID]

        addon2 = addon_factory(name='Fírefox Addôn', promoted=RECOMMENDED)
        ApplicationsVersions.objects.get_or_create(
            application=amo.ANDROID.id,
            version=addon2.current_version,
            min=av_min,
            max=av_max,
        )
        # This case is approved for all apps, but now only set for Firefox
        addon2.promotedaddon.update(application_id=amo.FIREFOX.id)
        assert addon2.promoted_group() == RECOMMENDED
        assert addon2.promotedaddon.application_id is amo.FIREFOX.id
        assert addon2.promotedaddon.approved_applications == [amo.FIREFOX]

        addon3 = addon_factory(slug='other-addon', name='Other Addôn')
        ApplicationsVersions.objects.get_or_create(
            application=amo.ANDROID.id,
            version=addon3.current_version,
            min=av_min,
            max=av_max,
        )

        # This is the opposite of addon2 -
        # originally approved just for Firefox but now set for all apps.
        addon4 = addon_factory(name='Fírefox Addôn with Android')
        ApplicationsVersions.objects.get_or_create(
            application=amo.ANDROID.id,
            version=addon4.current_version,
            min=av_min,
            max=av_max,
        )
        self.make_addon_promoted(addon4, RECOMMENDED)
        addon4.promotedaddon.update(application_id=amo.FIREFOX.id)
        addon4.promotedaddon.approve_for_version(addon4.current_version)
        addon4.promotedaddon.update(application_id=None)
        assert addon4.promoted_group() == RECOMMENDED
        assert addon4.promotedaddon.application_id is None  # i.e. all
        assert addon4.promotedaddon.approved_applications == [amo.FIREFOX]

        # And repeat with Android rather than Firefox
        addon5 = addon_factory(name='Andróid Addôn')
        ApplicationsVersions.objects.get_or_create(
            application=amo.ANDROID.id,
            version=addon5.current_version,
            min=av_min,
            max=av_max,
        )
        self.make_addon_promoted(addon5, RECOMMENDED)
        addon5.promotedaddon.update(application_id=amo.ANDROID.id)
        addon5.promotedaddon.approve_for_version(addon5.current_version)
        addon5.promotedaddon.update(application_id=None)
        assert addon5.promoted_group() == RECOMMENDED
        assert addon5.promotedaddon.application_id is None  # i.e. all
        assert addon5.promotedaddon.approved_applications == [amo.ANDROID]

        self.reindex(Addon)

        data = self.perform_search(self.url, {'promoted': 'recommended'})
        assert data['count'] == 4
        assert len(data['results']) == 4
        assert {res['id'] for res in data['results']} == {
            addon.pk,
            addon2.pk,
            addon4.pk,
            addon5.pk,
        }

        # And with app filtering too
        data = self.perform_search(
            self.url, {'promoted': 'recommended', 'app': 'firefox'}
        )
        assert data['count'] == 3
        assert len(data['results']) == 3
        assert {res['id'] for res in data['results']} == {
            addon.pk,
            addon2.pk,
            addon4.pk,
        }

        # That will filter out for a different app
        data = self.perform_search(
            self.url, {'promoted': 'recommended', 'app': 'android'}
        )
        assert data['count'] == 2
        assert len(data['results']) == 2
        assert {res['id'] for res in data['results']} == {addon.pk, addon5.pk}

        # test with other other promotions
        for promo in (SPONSORED, VERIFIED, LINE, SPOTLIGHT, STRATEGIC):
            self.make_addon_promoted(addon, promo, approve_version=True)
            self.reindex(Addon)
            data = self.perform_search(
                self.url, {'promoted': promo.api_name, 'app': 'firefox'}
            )
            assert data['count'] == 1
            assert len(data['results']) == 1
            assert data['results'][0]['id'] == addon.pk

    def test_filter_by_app(self):
        addon = addon_factory(
            slug='my-addon',
            name='My Addôn',
            popularity=33,
            version_kw={'min_app_version': '119.0', 'max_app_version': '*'},
        )
        an_addon = addon_factory(
            slug='my-tb-addon',
            name='My ANd Addøn',
            popularity=22,
            version_kw={
                'application': amo.ANDROID.id,
                'min_app_version': '121.0',
                'max_app_version': '*',
            },
        )
        both_addon = addon_factory(
            slug='my-both-addon',
            name='My Both Addøn',
            popularity=11,
            version_kw={'min_app_version': '121.0', 'max_app_version': '*'},
        )
        # both_addon was created with firefox compatibility, manually add
        # android, making it compatible with both.
        ApplicationsVersions.objects.create(
            application=amo.ANDROID.id,
            version=both_addon.current_version,
            min=AppVersion.objects.get_or_create(
                application=amo.ANDROID.id, version='121.0'
            )[0],
            max=AppVersion.objects.get(application=amo.ANDROID.id, version='*'),
        )
        # Because the manually created ApplicationsVersions was created after
        # the initial save, we need to reindex and not just refresh.
        self.reindex(Addon)

        data = self.perform_search(self.url, {'app': 'firefox'})
        assert data['count'] == 2
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == addon.pk
        assert data['results'][1]['id'] == both_addon.pk

        data = self.perform_search(self.url, {'app': 'android'})
        assert data['count'] == 2
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == an_addon.pk
        assert data['results'][1]['id'] == both_addon.pk

    def test_filter_by_appversion(self):
        addon = addon_factory(
            slug='my-addon',
            name='My Addôn',
            popularity=33,
            version_kw={'min_app_version': '121.0', 'max_app_version': '*'},
        )
        an_addon = addon_factory(
            slug='my-android-addon',
            name='My ANd Addøn',
            popularity=22,
            version_kw={
                'application': amo.ANDROID.id,
                'min_app_version': '121.0',
                'max_app_version': '*',
            },
        )
        both_addon = addon_factory(
            slug='my-both-addon',
            name='My Both Addøn',
            popularity=11,
            version_kw={'min_app_version': '122.0', 'max_app_version': '*'},
        )
        # both_addon was created with firefox compatibility, manually add
        # android, making it compatible with both.
        ApplicationsVersions.objects.create(
            application=amo.ANDROID.id,
            version=both_addon.current_version,
            min=AppVersion.objects.get_or_create(
                application=amo.ANDROID.id, version='122.0'
            )[0],
            max=AppVersion.objects.get(application=amo.ANDROID.id, version='*'),
        )
        # Because the manually created ApplicationsVersions was created after
        # the initial save, we need to reindex and not just refresh.
        self.reindex(Addon)

        data = self.perform_search(self.url, {'app': 'firefox', 'appversion': '123.0'})
        assert data['count'] == 2
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == addon.pk
        assert data['results'][1]['id'] == both_addon.pk

        data = self.perform_search(
            self.url, {'app': 'android', 'appversion': '122.0.1'}
        )
        assert data['count'] == 2
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == an_addon.pk
        assert data['results'][1]['id'] == both_addon.pk

        data = self.perform_search(self.url, {'app': 'firefox', 'appversion': '121.0'})
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == addon.pk

        data = self.perform_search(
            self.url, {'app': 'android', 'appversion': '121.0.1'}
        )
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == an_addon.pk

    def test_filter_by_appversion_100(self):
        addon = addon_factory(
            slug='my-addon',
            name='My Addôn',
            popularity=100,
            version_kw={'min_app_version': '100.0', 'max_app_version': '*'},
        )
        addon_factory(
            slug='my-second-addon',
            name='My Sécond Addôn',
            popularity=101,
            version_kw={'min_app_version': '101.0', 'max_app_version': '*'},
        )
        self.refresh()
        data = self.perform_search(self.url, {'app': 'firefox', 'appversion': '100.0'})
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == addon.pk

    def test_filter_by_category(self):
        category = CATEGORIES[amo.ADDON_EXTENSION]['alerts-updates']
        addon = addon_factory(slug='my-addon', name='My Addôn', category=category)

        self.refresh()

        # Create an add-on in a different category.
        other_category = CATEGORIES[amo.ADDON_EXTENSION]['tabs']
        addon_factory(slug='different-addon', category=other_category)

        self.refresh()

        # Search for add-ons in the first category. There should be only one.
        data = self.perform_search(
            self.url, {'app': 'firefox', 'type': 'extension', 'category': category.slug}
        )
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == addon.pk

    def test_filter_by_category_multiple_types(self):
        def get_category(type_, name):
            return CATEGORIES[type_][name]

        addon_ext = addon_factory(
            slug='my-addon-ext',
            name='My Addôn Ext',
            category=get_category(amo.ADDON_EXTENSION, 'other'),
            type=amo.ADDON_EXTENSION,
        )
        addon_st = addon_factory(
            slug='my-addon-st',
            name='My Addôn ST',
            category=get_category(amo.ADDON_STATICTHEME, 'other'),
            type=amo.ADDON_STATICTHEME,
        )

        self.refresh()

        # Create some add-ons in a different category.
        addon_factory(
            slug='different-addon-ext',
            name='Diff Addôn Ext',
            category=get_category(amo.ADDON_EXTENSION, 'tabs'),
            type=amo.ADDON_EXTENSION,
        )
        addon_factory(
            slug='different-addon-st',
            name='Diff Addôn ST',
            category=get_category(amo.ADDON_STATICTHEME, 'sports'),
            type=amo.ADDON_STATICTHEME,
        )

        self.refresh()

        # Search for add-ons in the first category. There should be two.
        data = self.perform_search(
            self.url,
            {'app': 'firefox', 'type': 'extension,statictheme', 'category': 'other'},
        )
        assert data['count'] == 2
        assert len(data['results']) == 2
        result_ids = (data['results'][0]['id'], data['results'][1]['id'])
        assert sorted(result_ids) == [addon_ext.pk, addon_st.pk]

    def test_filter_with_tags(self):
        addon = addon_factory(
            slug='my-addon', name='My Addôn', tags=['some_tag'], popularity=999
        )
        addon2 = addon_factory(
            slug='another-addon',
            name='Another Addôn',
            tags=['unique_tag', 'some_tag'],
            popularity=333,
        )
        addon3 = addon_factory(slug='unrelated', name='Unrelated', tags=['unrelated'])
        self.refresh()

        data = self.perform_search(self.url, {'tag': 'some_tag'})
        assert data['count'] == 2
        assert len(data['results']) == 2

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['slug'] == addon.slug
        assert result['tags'] == ['some_tag']
        result = data['results'][1]
        assert result['id'] == addon2.pk
        assert result['slug'] == addon2.slug
        assert result['tags'] == ['some_tag', 'unique_tag']

        data = self.perform_search(self.url, {'tag': 'unrelated'})
        assert data['count'] == 1
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon3.pk
        assert result['slug'] == addon3.slug
        assert result['tags'] == ['unrelated']

        data = self.perform_search(self.url, {'tag': 'unique_tag,some_tag'})
        assert data['count'] == 1
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon2.pk
        assert result['slug'] == addon2.slug
        assert result['tags'] == ['some_tag', 'unique_tag']

    def test_bad_filter(self):
        data = self.perform_search(self.url, {'app': 'lol'}, expected_status=400)
        assert data == ['Invalid "app" parameter.']

    def test_filter_by_author(self):
        author = user_factory(username='my-fancyAuthôr')
        addon = addon_factory(
            slug='my-addon', name='My Addôn', tags=['some_tag'], popularity=999
        )
        AddonUser.objects.create(addon=addon, user=author)
        addon2 = addon_factory(
            slug='another-addon',
            name='Another Addôn',
            tags=['unique_tag', 'some_tag'],
            popularity=333,
        )
        author2 = user_factory(username='my-FancyAuthôrName')
        AddonUser.objects.create(addon=addon2, user=author2)
        self.reindex(Addon)

        data = self.perform_search(self.url, {'author': 'my-fancyAuthôr'})
        assert data['count'] == 1
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['slug'] == addon.slug

    def test_filter_by_multiple_authors(self):
        author = user_factory(username='foo')
        author2 = user_factory(username='bar')
        another_author = user_factory(username='someoneelse')
        addon = addon_factory(
            slug='my-addon', name='My Addôn', tags=['some_tag'], popularity=999
        )
        AddonUser.objects.create(addon=addon, user=author)
        AddonUser.objects.create(addon=addon, user=author2)
        addon2 = addon_factory(
            slug='another-addon',
            name='Another Addôn',
            tags=['unique_tag', 'some_tag'],
            popularity=333,
        )
        AddonUser.objects.create(addon=addon2, user=author2)
        another_addon = addon_factory()
        AddonUser.objects.create(addon=another_addon, user=another_author)
        self.reindex(Addon)

        data = self.perform_search(self.url, {'author': 'foo,bar'})
        assert data['count'] == 2
        assert len(data['results']) == 2

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['slug'] == addon.slug
        result = data['results'][1]
        assert result['id'] == addon2.pk
        assert result['slug'] == addon2.slug

        # repeat with author ids
        data = self.perform_search(self.url, {'author': f'{author.pk},{author2.pk}'})
        assert data['count'] == 2
        assert len(data['results']) == 2

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['slug'] == addon.slug
        result = data['results'][1]
        assert result['id'] == addon2.pk
        assert result['slug'] == addon2.slug

        # and mixed username and ids
        data = self.perform_search(
            self.url, {'author': f'{author.pk},{author2.username}'}
        )
        assert data['count'] == 2
        assert len(data['results']) == 2

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['slug'] == addon.slug
        result = data['results'][1]
        assert result['id'] == addon2.pk
        assert result['slug'] == addon2.slug

    def test_filter_by_guid(self):
        addon = addon_factory(
            slug='my-addon', name='My Addôn', guid='random@guid', popularity=999
        )
        addon_factory()
        self.reindex(Addon)

        data = self.perform_search(self.url, {'guid': 'random@guid'})
        assert data['count'] == 1
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['slug'] == addon.slug

    def test_filter_by_multiple_guid(self):
        addon = addon_factory(
            slug='my-addon', name='My Addôn', guid='random@guid', popularity=999
        )
        addon2 = addon_factory(
            slug='another-addon',
            name='Another Addôn',
            guid='random2@guid',
            popularity=333,
        )
        addon_factory()
        self.reindex(Addon)

        data = self.perform_search(self.url, {'guid': 'random@guid,random2@guid'})
        assert data['count'] == 2
        assert len(data['results']) == 2

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['slug'] == addon.slug
        result = data['results'][1]
        assert result['id'] == addon2.pk
        assert result['slug'] == addon2.slug

        # Throw in soome random invalid guids too that will be ignored.
        data = self.perform_search(
            self.url, {'guid': 'random@guid,invalid@guid,notevenaguid$,random2@guid'}
        )
        assert data['count'] == len(data['results']) == 2
        assert data['results'][0]['id'] == addon.pk
        assert data['results'][1]['id'] == addon2.pk

    def test_filter_by_guid_return_to_amo(self):
        addon = addon_factory(
            slug='my-addon',
            name='My Addôn',
            guid='random@guid',
            popularity=999,
            promoted=RECOMMENDED,
        )
        addon_factory()
        self.reindex(Addon)

        param = 'rta:%s' % urlsafe_base64_encode(force_bytes(addon.guid))
        data = self.perform_search(self.url, {'guid': param})
        assert data['count'] == 1
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['slug'] == addon.slug

    def test_filter_by_guid_return_to_amo_not_promoted(self):
        addon = addon_factory(
            slug='my-addon', name='My Addôn', guid='random@guid', popularity=999
        )
        addon_factory()
        self.reindex(Addon)

        param = 'rta:%s' % urlsafe_base64_encode(force_bytes(addon.guid))
        data = self.perform_search(self.url, {'guid': param})
        assert data['count'] == 0
        assert data['results'] == []

    @override_switch('return-to-amo-for-all-listed', active=True)
    def test_filter_by_guid_return_to_amo_all_listed_enabled(self):
        assert switch_is_active('return-to-amo-for-all-listed')
        addon = addon_factory(
            slug='my-addon', name='My Addôn', guid='random@guid', popularity=999
        )
        addon_factory()
        self.reindex(Addon)

        param = 'rta:%s' % urlsafe_base64_encode(force_bytes(addon.guid))
        data = self.perform_search(self.url, {'guid': param})
        assert data['count'] == 1
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['slug'] == addon.slug

    def test_filter_by_guid_return_to_amo_wrong_format(self):
        param = 'rta:%s' % urlsafe_base64_encode(b'foo@bar')[:-1]
        data = self.perform_search(self.url, {'guid': param}, expected_status=400)
        assert data == ['Invalid Return To AMO guid (not in base64url format?)']

    def test_filter_by_guid_return_to_amo_garbage(self):
        # 'garbage' does decode using base64, but would lead to an
        # UnicodeDecodeError - invalid start byte.
        param = 'rta:garbage'
        data = self.perform_search(self.url, {'guid': param}, expected_status=400)
        assert data == ['Invalid Return To AMO guid (not in base64url format?)']

        # Empty param is just as bad.
        param = 'rta:'
        data = self.perform_search(self.url, {'guid': param}, expected_status=400)
        assert data == ['Invalid Return To AMO guid (not in base64url format?)']

    def test_filter_by_guid_return_to_amo_feature_disabled(self):
        self.create_switch('return-to-amo', active=False)
        assert not switch_is_active('return-to-amo')
        addon = addon_factory(
            slug='my-addon', name='My Addôn', guid='random@guid', popularity=999
        )
        addon_factory()
        self.reindex(Addon)

        param = 'rta:%s' % urlsafe_base64_encode(force_bytes(addon.guid))
        data = self.perform_search(self.url, {'guid': param}, expected_status=400)
        assert data == ['Return To AMO is currently disabled']

    def test_find_addon_default_non_en_us(self):
        with self.activate('en-GB'):
            addon = addon_factory(
                status=amo.STATUS_APPROVED,
                type=amo.ADDON_EXTENSION,
                default_locale='en-GB',
                name='Banana Bonkers',
                description='Let your browser eat your bananas',
                summary='Banana Summary',
            )

            addon.name = {'es': 'Banana Bonkers espanole'}
            addon.description = {'es': 'Deje que su navegador coma sus plátanos'}
            addon.summary = {'es': 'resumen banana'}
            addon.save()

        addon_factory(slug='English Addon', name='My English Addôn')

        self.reindex(Addon)

        for locale in ('en-US', 'en-GB', 'es'):
            with self.activate(locale):
                url = reverse_ns('addon-search')

                data = self.perform_search(url, {'lang': locale})

                assert data['count'] == 2
                assert len(data['results']) == 2

                data = self.perform_search(url, {'q': 'Banana', 'lang': locale})

                result = data['results'][0]
                assert result['id'] == addon.pk
                assert result['slug'] == addon.slug

    def test_exclude_addons(self):
        addon1 = addon_factory()
        addon2 = addon_factory()
        addon3 = addon_factory()
        self.refresh()

        # Exclude addon2 and addon3 by slug.
        data = self.perform_search(
            self.url, {'exclude_addons': ','.join((addon2.slug, addon3.slug))}
        )

        assert len(data['results']) == 1
        assert data['count'] == 1
        assert data['results'][0]['id'] == addon1.pk

        # Exclude addon1 and addon2 by pk.
        data = self.perform_search(
            self.url, {'exclude_addons': ','.join(map(str, (addon2.pk, addon1.pk)))}
        )

        assert len(data['results']) == 1
        assert data['count'] == 1
        assert data['results'][0]['id'] == addon3.pk

        # Exclude addon1 by pk and addon3 by slug.
        data = self.perform_search(
            self.url, {'exclude_addons': ','.join((str(addon1.pk), addon3.slug))}
        )

        assert len(data['results']) == 1
        assert data['count'] == 1
        assert data['results'][0]['id'] == addon2.pk

    def test_filter_fuzziness(self):
        with self.activate('de'):
            addon = addon_factory(
                slug='my-addon', name={'de': 'Mein Taschenmesser'}, default_locale='de'
            )

            # Won't get matched, we have a prefix length of 4 so that
            # the first 4 characters are not analyzed for fuzziness
            addon_factory(
                slug='my-addon2',
                name={'de': 'Mein Hufrinnenmesser'},
                default_locale='de',
            )

        self.refresh()

        with self.activate('de'):
            data = self.perform_search(self.url, {'q': 'Taschenmssser'})

        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == addon.pk

    def test_prevent_too_complex_to_determinize_exception(self):
        # too_complex_to_determinize_exception happens in elasticsearch when
        # we do a fuzzy query with a query string that is well, too complex,
        # with specific unicode chars and too long. For this reason we
        # deactivate fuzzy matching if the query is over 20 chars. This test
        # contain a string that was causing such breakage before.
        # Populate the index with a few add-ons first (enough to trigger the
        # issue locally).
        for _i in range(0, 10):
            addon_factory()
        self.refresh()
        query = '남포역립카페추천 ˇjjtat닷컴ˇ ≡제이제이♠♣ 남포역스파 남포역op남포역유흥≡남포역안마남포역오피 ♠♣'  # noqa: E501
        data = self.perform_search(self.url, {'q': query})
        # No results, but no 500 either.
        assert data['count'] == 0

    def test_with_recommended_addons(self):
        addon1 = addon_factory(popularity=666)
        addon2 = addon_factory(popularity=555)
        addon3 = addon_factory(popularity=444)
        addon4 = addon_factory(popularity=333)
        addon5 = addon_factory(popularity=222)
        self.refresh()

        # Default case first - no recommended addons
        data = self.perform_search(self.url)  # No query.

        ids = [result['id'] for result in data['results']]
        assert ids == [addon1.id, addon2.id, addon3.id, addon4.id, addon5.id]

        # Now made some of the add-ons recommended
        self.make_addon_promoted(addon2, RECOMMENDED, approve_version=True)
        self.make_addon_promoted(addon4, RECOMMENDED, approve_version=True)
        self.refresh()

        data = self.perform_search(self.url)  # No query.

        ids = [result['id'] for result in data['results']]
        # addon2 and addon4 will be first because they're recommended
        assert ids == [addon2.id, addon4.id, addon1.id, addon3.id, addon5.id]

    def test_filter_by_ratings(self):
        addon1 = addon_factory(popularity=666)
        addon2 = addon_factory(popularity=555)
        addon_factory(popularity=444)

        Rating.objects.create(addon=addon1, user=user_factory(), rating=1)
        Rating.objects.create(addon=addon1, user=user_factory(), rating=2)
        Rating.objects.create(addon=addon2, user=user_factory(), rating=1)

        self.refresh()

        data = self.perform_search(self.url, {'ratings__gt': 1.0})
        ids = [result['id'] for result in data['results']]
        # addon1 will be returned because it has an average rating higher than
        # the request. addon2 doesn't, and addon3 doesn't have ratings, so they
        # should not be present.
        assert ids == [addon1.id]


class TestAddonAutoCompleteSearchView(ESTestCase):
    client_class = APITestClientSessionID

    fixtures = ['base/users']

    def setUp(self):
        super().setUp()
        self.url = reverse_ns('addon-autocomplete', api_version='v5')

    def tearDown(self):
        super().tearDown()
        self.empty_index('default')
        self.refresh()

    def perform_search(self, url, data=None, expected_status=200, **headers):
        with self.assertNumQueries(0):
            response = self.client.get(url, data, **headers)
        assert response.status_code == expected_status
        data = json.loads(force_str(response.content))
        return data

    def test_basic(self):
        addon = addon_factory(slug='my-addon', name='My Addôn')
        addon2 = addon_factory(slug='my-second-addon', name='My second Addôn')
        addon_factory(slug='nonsense', name='Nope Nope Nope')
        self.refresh()

        data = self.perform_search(self.url, {'q': 'my'})  # No db query.
        assert 'count' not in data
        assert 'next' not in data
        assert 'prev' not in data
        assert len(data['results']) == 2

        assert {itm['id'] for itm in data['results']} == {addon.pk, addon2.pk}

    def test_type(self):
        addon = addon_factory(
            slug='my-addon', name='My Addôn', type=amo.ADDON_EXTENSION
        )
        addon2 = addon_factory(
            slug='my-second-addon', name='My second Addôn', type=amo.ADDON_STATICTHEME
        )
        addon_factory(slug='nonsense', name='Nope Nope Nope')
        addon_factory(slug='whocares', name='My dict', type=amo.ADDON_DICT)
        self.refresh()

        # No db query.
        data = self.perform_search(
            self.url, {'q': 'my', 'type': 'statictheme,extension'}
        )
        assert 'count' not in data
        assert 'next' not in data
        assert 'prev' not in data
        assert len(data['results']) == 2

        assert {itm['id'] for itm in data['results']} == {addon.pk, addon2.pk}

    def test_default_locale_fallback_still_works_for_translations(self):
        addon = addon_factory(default_locale='pt-BR', name='foobar')
        # Couple quick checks to make sure the add-on is in the right state
        # before testing.
        assert addon.default_locale == 'pt-BR'
        assert addon.name.locale == 'pt-br'

        self.refresh()

        # Search in a different language than the one used for the name: we
        # should fall back to default_locale and find the translation.
        data = self.perform_search(self.url, {'q': 'foobar', 'lang': 'fr'})
        assert data['results'][0]['name'] == {
            'pt-BR': 'foobar',
            'fr': None,
            '_default': 'pt-BR',
        }
        assert list(data['results'][0]['name'])[0] == 'pt-BR'

        # Same deal in en-US.
        data = self.perform_search(self.url, {'q': 'foobar', 'lang': 'en-US'})
        assert data['results'][0]['name'] == {
            'pt-BR': 'foobar',
            'en-US': None,
            '_default': 'pt-BR',
        }
        assert list(data['results'][0]['name'])[0] == 'pt-BR'

        # And repeat with v3-style flat output when lang is specified:
        overridden_api_gates = {'v5': ('l10n_flat_input_output',)}
        with override_settings(DRF_API_GATES=overridden_api_gates):
            data = self.perform_search(self.url, {'q': 'foobar', 'lang': 'fr'})
            assert data['results'][0]['name'] == 'foobar'

            data = self.perform_search(self.url, {'q': 'foobar', 'lang': 'en-US'})
            assert data['results'][0]['name'] == 'foobar'

    def test_empty(self):
        data = self.perform_search(self.url)
        assert 'count' not in data
        assert len(data['results']) == 0

    def test_get_queryset_excludes(self):
        addon_factory(slug='my-addon', name='My Addôn', popularity=666)
        addon_factory(slug='my-theme', name='My Th€me', type=amo.ADDON_STATICTHEME)
        self.refresh()

        view = AddonAutoCompleteSearchView()
        view.request = APIRequestFactory().get('/')
        qset = view.get_queryset()

        includes = {
            'current_version',
            'default_locale',
            'icon_type',
            'id',
            'modified',
            'name_translations',
            'promoted',
            'slug',
            'type',
        }

        assert set(qset.to_dict()['_source']['includes']) == includes

        response = qset.execute()

        # Sort by type to avoid sorting problems before picking the
        # first result. (We have a theme and an add-on)
        hit = sorted(response.hits.hits, key=lambda x: x['_source']['type'])
        assert set(hit[1]['_source'].to_dict().keys()) == includes

    def test_no_unlisted(self):
        addon_factory(
            slug='my-addon',
            name='My Addôn',
            status=amo.STATUS_NULL,
            popularity=666,
            version_kw={'channel': amo.CHANNEL_UNLISTED},
        )
        self.refresh()
        data = self.perform_search(self.url)
        assert 'count' not in data
        assert len(data['results']) == 0

    def test_pagination(self):
        [addon_factory() for x in range(0, 11)]
        self.refresh()

        # page_size should be ignored, we should get 10 results.
        data = self.perform_search(self.url, {'page_size': 1})
        assert 'count' not in data
        assert 'next' not in data
        assert 'prev' not in data
        assert len(data['results']) == 10

    def test_sort_ignored(self):
        addon = addon_factory(slug='my-addon', name='My Addôn', average_daily_users=100)
        addon2 = addon_factory(
            slug='my-second-addon', name='My second Addôn', average_daily_users=200
        )
        addon_factory(slug='nonsense', name='Nope Nope Nope')
        self.refresh()

        data = self.perform_search(self.url, {'q': 'my', 'sort': 'users'})
        assert 'count' not in data
        assert 'next' not in data
        assert 'prev' not in data
        assert len(data['results']) == 2

        assert {itm['id'] for itm in data['results']} == {addon2.pk, addon.pk}

        # check the sort isn't ignored when the gate is enabled
        overridden_api_gates = {'v5': ('autocomplete-sort-param',)}
        with override_settings(DRF_API_GATES=overridden_api_gates):
            data = self.perform_search(self.url, {'q': 'my', 'sort': 'users'})
            assert {itm['id'] for itm in data['results']} == {addon.pk, addon2.pk}

    def test_promoted(self):
        not_promoted = addon_factory(name='not promoted')
        sponsored = addon_factory(name='is promoted')
        self.make_addon_promoted(sponsored, SPONSORED, approve_version=True)
        addon_factory(name='something')

        self.refresh()

        data = self.perform_search(self.url, {'q': 'promoted'})  # No db query.
        assert 'count' not in data
        assert 'next' not in data
        assert 'prev' not in data
        assert len(data['results']) == 2

        assert {itm['id'] for itm in data['results']} == {not_promoted.pk, sponsored.pk}

        sponsored_result, not_result = (
            (data['results'][0], data['results'][1])
            if data['results'][0]['id'] == sponsored.id
            else (data['results'][1], data['results'][0])
        )
        assert sponsored_result['promoted']['category'] == 'sponsored'
        assert not_result['promoted'] is None


class TestAddonFeaturedView(ESTestCase):
    client_class = APITestClientSessionID

    fixtures = ['base/users']

    def setUp(self):
        super().setUp()
        # This api endpoint only still exists in v3.
        self.url = reverse_ns('addon-featured', api_version='v3')

    def tearDown(self):
        super().tearDown()
        self.empty_index('default')
        self.refresh()

    def test_basic(self):
        addon1 = addon_factory(promoted=RECOMMENDED)
        addon2 = addon_factory(promoted=RECOMMENDED)
        assert addon1.promoted_group() == RECOMMENDED
        assert addon2.promoted_group() == RECOMMENDED
        addon_factory()  # not recommended so shouldn't show up
        self.refresh()

        response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['results']
        assert len(data['results']) == 2
        # order is random
        ids = {result['id'] for result in data['results']}
        assert ids == {addon1.id, addon2.id}

    def test_page_size(self):
        for _ in range(0, 15):
            addon_factory(promoted=RECOMMENDED)

        self.refresh()

        # ask for > 10, to check we're not hitting the default ES page size.
        response = self.client.get(self.url + '?page_size=11')
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['results']
        assert len(data['results']) == 11

    def test_invalid_app(self):
        response = self.client.get(self.url, {'app': 'foxeh', 'type': 'extension'})
        assert response.status_code == 400
        assert json.loads(force_str(response.content)) == ['Invalid "app" parameter.']

    def test_invalid_type(self):
        response = self.client.get(self.url, {'app': 'firefox', 'type': 'lol'})
        assert response.status_code == 400
        assert json.loads(force_str(response.content)) == ['Invalid "type" parameter.']

    def test_invalid_category(self):
        response = self.client.get(
            self.url, {'category': 'lol', 'app': 'firefox', 'type': 'extension'}
        )
        assert response.status_code == 400
        assert json.loads(force_str(response.content)) == [
            'Invalid "category" parameter.'
        ]


class TestStaticCategoryView(TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        super().setUp()
        self.url = reverse_ns('category-list')

    def test_basic(self):
        with self.assertNumQueries(0):
            response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))

        assert len(data) == 32

        # some basic checks to verify integrity
        entry = data[0]

        assert entry == {
            'name': 'Feeds, News & Blogging',
            'weight': 0,
            'misc': False,
            'id': 1,
            'description': (
                'Download Firefox extensions that remove clutter so you '
                'can stay up-to-date on social media, catch up on blogs, '
                'RSS feeds, reduce eye strain, and more.'
            ),
            'type': 'extension',
            'slug': 'feeds-news-blogging',
        }

    def test_with_description(self):
        # StaticCategory is immutable, so avoid calling it's __setattr__
        # directly.
        object.__setattr__(CATEGORIES_BY_ID[1], 'description', 'does stuff')
        with self.assertNumQueries(0):
            response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))

        assert len(data) == 32

        # some basic checks to verify integrity
        entry = data[0]

        assert entry == {
            'name': 'Feeds, News & Blogging',
            'weight': 0,
            'misc': False,
            'id': 1,
            'description': 'does stuff',
            'type': 'extension',
            'slug': 'feeds-news-blogging',
        }

    @pytest.mark.needs_locales_compilation
    def test_name_translated(self):
        with self.assertNumQueries(0):
            response = self.client.get(self.url, HTTP_ACCEPT_LANGUAGE='de')

        assert response.status_code == 200
        data = json.loads(force_str(response.content))

        assert data[0]['name'] == 'RSS-Feeds, Nachrichten & Bloggen'

    def test_cache_control(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response['cache-control'] == 'max-age=21600'

    @override_settings(DRF_API_GATES={'v5': ('categories-application',)})
    def test_with_application(self):
        with self.assertNumQueries(0):
            response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data) == 32
        for entry in data:
            assert entry['application'] == 'firefox'


class TestLanguageToolsView(TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        super().setUp()
        self.url = reverse_ns('addon-language-tools')

    def test_wrong_app(self):
        response = self.client.get(self.url, {'app': 'foo', 'appversion': '57.0'})
        assert response.status_code == 400
        assert response.data == {
            'detail': 'Invalid or missing app parameter while appversion parameter '
            'is set.'
        }

    def test_basic(self):
        dictionary = addon_factory(type=amo.ADDON_DICT, target_locale='fr')
        dictionary_spelling_variant = addon_factory(
            type=amo.ADDON_DICT, target_locale='fr'
        )
        language_pack = addon_factory(
            type=amo.ADDON_LPAPP,
            target_locale='es',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'},
        )

        # These add-ons below should be ignored: they are either not public or
        # of the wrong type, or their target locale is empty.
        addon_factory(
            type=amo.ADDON_DICT,
            target_locale='fr',
            version_kw={'channel': amo.CHANNEL_UNLISTED},
        )
        addon_factory(
            type=amo.ADDON_LPAPP,
            target_locale='es',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            status=amo.STATUS_NOMINATED,
        )
        addon_factory(type=amo.ADDON_DICT, target_locale='')
        addon_factory(type=amo.ADDON_LPAPP, target_locale=None)
        addon_factory(target_locale='fr')

        response = self.client.get(self.url, {'app': 'firefox'})
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert len(data['results']) == 3
        expected = [dictionary, dictionary_spelling_variant, language_pack]
        assert len(data['results']) == len(expected)
        assert {item['id'] for item in data['results']} == {
            item.pk for item in expected
        }

        assert 'locale_disambiguation' not in data['results'][0]
        assert 'target_locale' in data['results'][0]
        # We were not filtering by appversion, so we do not get the
        # current_compatible_version property.
        assert 'current_compatible_version' not in data['results'][0]

    def test_with_appversion_but_no_type(self):
        response = self.client.get(self.url, {'app': 'firefox', 'appversion': '57.0'})
        assert response.status_code == 400
        assert response.data == {
            'detail': 'Invalid or missing type parameter while appversion '
            'parameter is set.'
        }

    def test_with_appversion_but_no_application(self):
        response = self.client.get(self.url, {'appversion': '57.0'})
        assert response.status_code == 400
        assert response.data == {
            'detail': 'Invalid or missing app parameter while appversion parameter '
            'is set.'
        }

    def test_with_invalid_appversion(self):
        response = self.client.get(
            self.url, {'app': 'firefox', 'type': 'language', 'appversion': 'foôbar'}
        )
        assert response.status_code == 400
        assert response.data == {'detail': 'Invalid appversion parameter.'}

    def test_with_author_filtering(self):
        user = user_factory(username='mozillä')
        addon1 = addon_factory(type=amo.ADDON_LPAPP, target_locale='de')
        addon2 = addon_factory(type=amo.ADDON_LPAPP, target_locale='fr')
        AddonUser.objects.create(addon=addon1, user=user)
        AddonUser.objects.create(addon=addon2, user=user)

        # These 2 should not show up: it's either not the right author, or
        # the author is not listed.
        addon3 = addon_factory(type=amo.ADDON_LPAPP, target_locale='es')
        AddonUser.objects.create(addon=addon3, user=user, listed=False)
        addon_factory(type=amo.ADDON_LPAPP, target_locale='it')

        response = self.client.get(
            self.url, {'app': 'firefox', 'type': 'language', 'author': 'mozillä'}
        )
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        expected = [addon1, addon2]

        assert len(data['results']) == len(expected)
        assert {item['id'] for item in data['results']} == {
            item.pk for item in expected
        }

    def test_with_multiple_authors_filtering(self):
        user1 = user_factory(username='mozillä')
        user2 = user_factory(username='firefôx')
        addon1 = addon_factory(type=amo.ADDON_LPAPP, target_locale='de')
        addon2 = addon_factory(type=amo.ADDON_LPAPP, target_locale='fr')
        AddonUser.objects.create(addon=addon1, user=user1)
        AddonUser.objects.create(addon=addon2, user=user2)

        # These 2 should not show up: it's either not the right author, or
        # the author is not listed.
        addon3 = addon_factory(type=amo.ADDON_LPAPP, target_locale='es')
        AddonUser.objects.create(addon=addon3, user=user1, listed=False)
        addon_factory(type=amo.ADDON_LPAPP, target_locale='it')

        response = self.client.get(
            self.url,
            {'app': 'firefox', 'type': 'language', 'author': 'mozillä,firefôx'},
        )
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        expected = [addon1, addon2]
        assert len(data['results']) == len(expected)
        assert {item['id'] for item in data['results']} == {
            item.pk for item in expected
        }

    def test_with_appversion_filtering(self):
        # Add compatible add-ons. We're going to request language packs
        # compatible with 58.0.
        compatible_pack1 = addon_factory(
            name='Spanish Language Pack',
            type=amo.ADDON_LPAPP,
            target_locale='es',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'},
        )
        compatible_pack1.current_version.update(created=self.days_ago(2))
        compatible_version1 = version_factory(
            addon=compatible_pack1,
            file_kw={'strict_compatibility': True},
            min_app_version='58.0',
            max_app_version='58.*',
        )
        compatible_version1.update(created=self.days_ago(1))
        compatible_pack2 = addon_factory(
            name='French Language Pack',
            type=amo.ADDON_LPAPP,
            target_locale='fr',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '58.0', 'max_app_version': '58.*'},
        )
        compatible_version2 = compatible_pack2.current_version
        compatible_version2.update(created=self.days_ago(1))
        version_factory(
            addon=compatible_pack2,
            file_kw={'strict_compatibility': True},
            min_app_version='59.0',
            max_app_version='59.*',
        )
        # Add a more recent version for both add-ons, that would be compatible
        # with 58.0, but is not public/listed so should not be returned.
        version_factory(
            addon=compatible_pack1,
            file_kw={'strict_compatibility': True},
            min_app_version='58.0',
            max_app_version='58.*',
            channel=amo.CHANNEL_UNLISTED,
        )
        version_factory(
            addon=compatible_pack2,
            file_kw={'strict_compatibility': True, 'status': amo.STATUS_DISABLED},
            min_app_version='58.0',
            max_app_version='58.*',
        )
        # And for the first pack, add a couple of versions that are also
        # compatible. We should not use them though, because we only need to
        # return the latest public version that is compatible.
        extra_compatible_version_1 = version_factory(
            addon=compatible_pack1,
            file_kw={'strict_compatibility': True},
            min_app_version='58.0',
            max_app_version='58.*',
        )
        extra_compatible_version_1.update(created=self.days_ago(3))
        extra_compatible_version_2 = version_factory(
            addon=compatible_pack1,
            file_kw={'strict_compatibility': True},
            min_app_version='58.0',
            max_app_version='58.*',
        )
        extra_compatible_version_2.update(created=self.days_ago(4))

        # Add a few of incompatible add-ons.
        incompatible_pack1 = addon_factory(
            name='German Language Pack (incompatible with 58.0)',
            type=amo.ADDON_LPAPP,
            target_locale='fr',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '56.0', 'max_app_version': '56.*'},
        )
        version_factory(
            addon=incompatible_pack1,
            file_kw={'strict_compatibility': True},
            min_app_version='59.0',
            max_app_version='59.*',
        )
        addon_factory(
            name='Italian Language Pack (incompatible with 58.0)',
            type=amo.ADDON_LPAPP,
            target_locale='it',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '59.0', 'max_app_version': '59.*'},
        )
        # Even add a pack with a compatible version... not public. And another
        # one with a compatible version... not listed.
        incompatible_pack2 = addon_factory(
            name='Japanese Language Pack (public, but 58.0 version is not)',
            type=amo.ADDON_LPAPP,
            target_locale='ja',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'},
        )
        version_factory(
            addon=incompatible_pack2,
            min_app_version='58.0',
            max_app_version='58.*',
            file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'strict_compatibility': True,
            },
        )
        incompatible_pack3 = addon_factory(
            name='Nederlands Language Pack (58.0 version is unlisted)',
            type=amo.ADDON_LPAPP,
            target_locale='ja',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'},
        )
        version_factory(
            addon=incompatible_pack3,
            min_app_version='58.0',
            max_app_version='58.*',
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'strict_compatibility': True},
        )

        # Test it.
        with self.assertNumQueries(4):
            # 4 queries, regardless of how many add-ons are returned:
            # - 1 for the add-ons
            # - 1 for the compatible version (through prefetch_related) and
            #     its file
            # - 1 for the applications versions
            # - 1 for the add-ons translations (name)
            response = self.client.get(
                self.url,
                {
                    'app': 'firefox',
                    'appversion': '58.0',
                    'type': 'language',
                    'lang': 'en-US',
                },
            )
        assert response.status_code == 200, response.content
        results = response.data['results']
        assert len(results) == 2

        # Ordering is not guaranteed by this API, but do check that the
        # current_compatible_version returned makes sense.
        assert results[0]['current_compatible_version']
        assert results[1]['current_compatible_version']

        expected_versions = {
            (compatible_pack1.pk, compatible_version1.pk),
            (compatible_pack2.pk, compatible_version2.pk),
        }
        returned_versions = {
            (results[0]['id'], results[0]['current_compatible_version']['id']),
            (results[1]['id'], results[1]['current_compatible_version']['id']),
        }
        assert expected_versions == returned_versions
        assert results[0]['current_compatible_version']['file']

        # repeat with v4 to check output is stable (it uses files rather than file)
        response = self.client.get(
            reverse_ns('addon-language-tools', api_version='v4'),
            {
                'app': 'firefox',
                'appversion': '58.0',
                'type': 'language',
                'lang': 'en-US',
            },
        )
        assert response.status_code == 200, response.content
        results = response.data['results']
        assert len(results) == 2
        assert results[0]['current_compatible_version']['files']

    def test_cache_headers(self):
        super_author = user_factory(username='super')
        addon_factory(type=amo.ADDON_DICT, target_locale='fr', users=(super_author,))
        addon_factory(type=amo.ADDON_DICT, target_locale='fr')
        addon_factory(type=amo.ADDON_LPAPP, target_locale='es', users=(super_author,))

        with self.assertNumQueries(2):
            response = self.client.get(self.url, {'app': 'firefox', 'lang': 'fr'})
        assert response.status_code == 200
        assert len(json.loads(force_str(response.content))['results']) == 3

        assert response['Cache-Control'] == 'max-age=86400'
        assert response['Vary'] == (
            'origin, Accept-Encoding, X-Country-Code, Accept-Language'
        )


class TestReplacementAddonView(TestCase):
    client_class = APITestClientSessionID

    def test_basic(self):
        # Add a single addon replacement
        rep_addon1 = addon_factory()
        ReplacementAddon.objects.create(
            guid='legacy2addon@moz', path=unquote(rep_addon1.get_url_path())
        )
        # Add a collection replacement
        author = user_factory()
        collection = collection_factory(author=author)
        rep_addon2 = addon_factory()
        rep_addon3 = addon_factory()
        CollectionAddon.objects.create(addon=rep_addon2, collection=collection)
        CollectionAddon.objects.create(addon=rep_addon3, collection=collection)
        ReplacementAddon.objects.create(
            guid='legacy2collection@moz', path=unquote(collection.get_url_path())
        )
        # Add an invalid path
        ReplacementAddon.objects.create(
            guid='notgonnawork@moz', path='/addon/áddonmissing/'
        )

        response = self.client.get(reverse_ns('addon-replacement-addon'))
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        results = data['results']
        assert len(results) == 3
        assert {'guid': 'legacy2addon@moz', 'replacement': [rep_addon1.guid]} in results
        assert {
            'guid': 'legacy2collection@moz',
            'replacement': [rep_addon2.guid, rep_addon3.guid],
        } in results
        assert {'guid': 'notgonnawork@moz', 'replacement': []} in results


class TestCompatOverrideView(TestCase):
    """This view is used by Firefox directly and queried a lot.

    But now we don't have any CompatOverrides we just return an empty response.
    """

    client_class = APITestClientSessionID

    def test_response(self):
        response = self.client.get(
            reverse_ns('addon-compat-override', api_version='v3'),
            data={'guid': 'extrabad@thing,bad@thing'},
        )
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        results = data['results']
        assert len(results) == 0


class TestAddonRecommendationView(ESTestCase):
    client_class = APITestClientSessionID

    fixtures = ['base/users']

    def setUp(self):
        super().setUp()
        self.url = reverse_ns('addon-recommendations')
        patcher = mock.patch('olympia.addons.views.get_addon_recommendations')
        self.get_addon_recommendations_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        super().tearDown()
        self.empty_index('default')
        self.refresh()

    def perform_search(self, url, data=None, expected_status=200, **headers):
        with self.assertNumQueries(0):
            response = self.client.get(url, data, **headers)
        assert response.status_code == expected_status, response.content
        data = json.loads(force_str(response.content))
        return data

    def test_invalid_guid(self):
        data = self.perform_search(self.url, expected_status=400)
        assert data['detail'] == 'Invalid guid parameter'

        data = self.perform_search(
            self.url, data={'guid': 'invalid'}, expected_status=400
        )
        assert data['detail'] == 'Invalid guid parameter'

        data = self.perform_search(
            self.url, data={'guid': "invalid@a' AND 1=1"}, expected_status=400
        )
        assert data['detail'] == 'Invalid guid parameter'

        data = self.perform_search(
            self.url,
            data={'guid': '{88291a20-a290-484a-a21a-6e1eaf38ee00} /* LOL */'},
            expected_status=400,
        )
        assert data['detail'] == 'Invalid guid parameter'

        data = self.perform_search(
            self.url,
            data={'guid': '88291a20a290484aa21a6e1eaf38ee00'},
            expected_status=400,
        )
        assert data['detail'] == 'Invalid guid parameter'

    def test_basic(self):
        addon1 = addon_factory(id=101, guid='101@mozilla')
        addon2 = addon_factory(id=102, guid='102@mozilla')
        addon3 = addon_factory(id=103, guid='103@mozilla')
        addon4 = addon_factory(id=104, guid='104@mozilla')
        self.get_addon_recommendations_mock.return_value = (
            ['101@mozilla', '102@mozilla', '103@mozilla', '104@mozilla'],
            'recommended',
            'no_reason',
        )
        self.refresh()

        data = self.perform_search(
            self.url, {'guid': 'foo@baa', 'recommended': 'False'}
        )
        self.get_addon_recommendations_mock.assert_called_with('foo@baa', False)
        assert data['outcome'] == 'recommended'
        assert data['fallback_reason'] == 'no_reason'
        assert data['count'] == 4
        assert len(data['results']) == 4

        result = data['results'][0]
        assert result['id'] == addon1.pk
        assert result['guid'] == '101@mozilla'
        result = data['results'][1]
        assert result['id'] == addon2.pk
        assert result['guid'] == '102@mozilla'
        result = data['results'][2]
        assert result['id'] == addon3.pk
        assert result['guid'] == '103@mozilla'
        result = data['results'][3]
        assert result['id'] == addon4.pk
        assert result['guid'] == '104@mozilla'

    @mock.patch('olympia.addons.views.get_addon_recommendations_invalid')
    def test_less_than_four_results(self, get_addon_recommendations_invalid):
        addon1 = addon_factory(id=101, guid='101@mozilla')
        addon2 = addon_factory(id=102, guid='102@mozilla')
        addon3 = addon_factory(id=103, guid='103@mozilla')
        addon4 = addon_factory(id=104, guid='104@mozilla')
        addon5 = addon_factory(id=105, guid='105@mozilla')
        addon6 = addon_factory(id=106, guid='106@mozilla')
        addon7 = addon_factory(id=107, guid='107@mozilla')
        addon8 = addon_factory(id=108, guid='108@mozilla')
        self.get_addon_recommendations_mock.return_value = (
            ['101@mozilla', '102@mozilla', '103@mozilla', '104@mozilla'],
            'recommended',
            None,
        )
        get_addon_recommendations_invalid.return_value = (
            ['105@mozilla', '106@mozilla', '107@mozilla', '108@mozilla'],
            'failed',
            'invalid',
        )
        self.refresh()

        data = self.perform_search(self.url, {'guid': 'foo@baa', 'recommended': 'True'})
        self.get_addon_recommendations_mock.assert_called_with('foo@baa', True)
        assert data['outcome'] == 'recommended'
        assert data['fallback_reason'] is None
        assert data['count'] == 4
        assert len(data['results']) == 4

        result = data['results'][0]
        assert result['id'] == addon1.pk
        assert result['guid'] == '101@mozilla'
        result = data['results'][1]
        assert result['id'] == addon2.pk
        assert result['guid'] == '102@mozilla'
        result = data['results'][2]
        assert result['id'] == addon3.pk
        assert result['guid'] == '103@mozilla'
        result = data['results'][3]
        assert result['id'] == addon4.pk
        assert result['guid'] == '104@mozilla'

        # Delete one of the add-ons returned, making us use curated fallbacks
        addon1.delete()
        self.refresh()
        data = self.perform_search(self.url, {'guid': 'foo@baa', 'recommended': 'True'})
        self.get_addon_recommendations_mock.assert_called_with('foo@baa', True)
        assert data['outcome'] == 'failed'
        assert data['fallback_reason'] == 'invalid'
        assert data['count'] == 4
        assert len(data['results']) == 4

        result = data['results'][0]
        assert result['id'] == addon5.pk
        assert result['guid'] == '105@mozilla'
        result = data['results'][1]
        assert result['id'] == addon6.pk
        assert result['guid'] == '106@mozilla'
        result = data['results'][2]
        assert result['id'] == addon7.pk
        assert result['guid'] == '107@mozilla'
        result = data['results'][3]
        assert result['id'] == addon8.pk
        assert result['guid'] == '108@mozilla'

    def test_es_queries_made_no_results(self):
        self.get_addon_recommendations_mock.return_value = (['@a', '@b'], 'foo', 'baa')
        with patch.object(
            Elasticsearch, 'search', wraps=get_es().search
        ) as search_mock:
            with patch.object(
                Elasticsearch, 'count', wraps=get_es().count
            ) as count_mock:
                data = self.perform_search(self.url, data={'guid': '@foo'})
                assert data['count'] == 0
                assert len(data['results']) == 0
                assert search_mock.call_count == 1
                assert count_mock.call_count == 0

    def test_es_queries_made_results(self):
        addon_factory(slug='foormidable', name='foo', guid='@a')
        addon_factory(slug='foobar', name='foo', guid='@b')
        addon_factory(slug='fbar', name='foo', guid='@c')
        addon_factory(slug='fb', name='foo', guid='@d')
        self.refresh()

        self.get_addon_recommendations_mock.return_value = (
            ['@a', '@b', '@c', '@d'],
            'recommended',
            None,
        )
        with patch.object(
            Elasticsearch, 'search', wraps=get_es().search
        ) as search_mock:
            with patch.object(
                Elasticsearch, 'count', wraps=get_es().count
            ) as count_mock:
                data = self.perform_search(
                    self.url, data={'guid': '@foo', 'recommended': 'true'}
                )
                assert data['count'] == 4
                assert len(data['results']) == 4
                assert search_mock.call_count == 1
                assert count_mock.call_count == 0


class TestAddonPreviewViewSet(TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        self.user = user_factory(read_dev_agreement=self.days_ago(0))
        self.addon = addon_factory(users=(self.user,))

    @override_settings(API_THROTTLING=False)
    @mock.patch('olympia.addons.serializers.resize_preview.delay')
    def test_create(self, resize_preview_mock):
        def post_with_error(filename):
            response = self.client.post(
                url, data={'image': _get_upload(filename)}, format='multipart'
            )
            assert response.status_code == 400, response.content
            return response.data['image']

        url = reverse_ns(
            'addon-preview-list',
            kwargs={'addon_pk': self.addon.id},
            api_version='v5',
        )

        response = self.client.post(
            url, data={'image': _get_upload('mozilla-sq.png')}, format='multipart'
        )
        assert response.status_code == 401, response.content

        self.client.login_api(self.user)
        assert post_with_error('non-animated.gif') == [
            'Images must be either PNG or JPG.'
        ]
        assert post_with_error('animated.png') == ['Images cannot be animated.']
        with override_settings(MAX_IMAGE_UPLOAD_SIZE=100):
            assert post_with_error('preview.jpg') == [
                'Images must be smaller than 0MB',
            ]

        assert not self.addon.previews.exists()
        response = self.client.post(
            url,
            data={'image': _get_upload('preview.jpg')},
            format='multipart',
        )
        assert response.status_code == 201, response.content

        self.addon.reload()
        preview = self.addon.previews.get()
        assert response.data == {
            'caption': None,
            'id': preview.id,
            'image_size': [],
            'image_url': absolutify(preview.image_url),
            'position': 0,
            'thumbnail_size': [],
            'thumbnail_url': absolutify(preview.thumbnail_url),
        }
        resize_preview_mock.assert_called_with(
            preview.original_path,
            preview.id,
            set_modified_on=self.addon.serializable_reference(),
        )
        assert os.path.exists(preview.original_path)
        alog = ActivityLog.objects.get()
        assert alog.user == self.user
        assert alog.action == amo.LOG.CHANGE_MEDIA.id
        assert alog.addonlog_set.get().addon == self.addon

    def test_cannot_create_for_themes(self):
        self.client.login_api(self.user)
        self.addon.update(type=amo.ADDON_STATICTHEME)
        url = reverse_ns(
            'addon-preview-list',
            kwargs={'addon_pk': self.addon.id},
            api_version='v5',
        )
        response = self.client.post(
            url,
            data={'image': _get_upload('preview.jpg')},
            format='multipart',
        )
        assert response.status_code == 400, response.content
        assert response.data == {
            'non_field_errors': ['Previews cannot be created for themes.']
        }

        self.addon.reload()
        assert not self.addon.previews.exists()
        assert not Preview.objects.filter(addon=self.addon).exists()
        assert not VersionPreview.objects.filter(
            version=self.addon.current_version
        ).exists()

    @mock.patch('olympia.addons.serializers.resize_preview.delay')
    def test_cannot_update_image(self, resize_preview_mock):
        self.client.login_api(self.user)
        preview = Preview.objects.create(addon=self.addon)
        url = reverse_ns(
            'addon-preview-detail',
            kwargs={'addon_pk': self.addon.id, 'pk': preview.id},
            api_version='v5',
        )
        response = self.client.patch(
            url,
            data={'image': _get_upload('preview.jpg')},
            format='multipart',
        )
        assert response.status_code == 200, response.content

        resize_preview_mock.assert_not_called()

    def test_update(self):
        preview = Preview.objects.create(addon=self.addon)
        url = reverse_ns(
            'addon-preview-detail',
            kwargs={'addon_pk': self.addon.id, 'pk': preview.id},
            api_version='v5',
        )
        data = {'caption': {'en-US': 'a thing', 'fr': 'un thíng'}, 'position': 1}

        # can't patch if not authenticated
        response = self.client.patch(url, data=data)
        assert response.status_code == 401

        # can't patch if not your add-on
        self.client.login_api(user_factory())
        response = self.client.patch(url, data=data)
        assert response.status_code == 403

        self.client.login_api(self.user)
        response = self.client.patch(url, data=data)
        assert response.status_code == 200
        preview.reload()
        assert response.data['caption'] == {'en-US': 'a thing', 'fr': 'un thíng'}
        assert response.data['position'] == preview.position == 1
        assert preview.caption == 'a thing'
        alog = ActivityLog.objects.get()
        assert alog.user == self.user
        assert alog.action == amo.LOG.CHANGE_MEDIA.id
        assert alog.addonlog_set.get().addon == self.addon

    def test_caption_too_long(self):
        preview = Preview.objects.create(addon=self.addon)
        url = reverse_ns(
            'addon-preview-detail',
            kwargs={'addon_pk': self.addon.id, 'pk': preview.id},
            api_version='v5',
        )
        data = {'caption': {'en-US': 'ĉ' * 281, 'fr': 'un thíng'}, 'position': 1}
        self.client.login_api(self.user)
        response = self.client.patch(url, data=data)
        assert response.status_code == 400
        assert response.data == {
            'caption': [
                ErrorDetail(
                    string='Ensure this field has no more than 280 characters.',
                    code='max_length',
                )
            ]
        }

    def test_delete(self):
        preview = Preview.objects.create(addon=self.addon)
        url = reverse_ns(
            'addon-preview-detail', kwargs={'addon_pk': self.addon.id, 'pk': preview.id}
        )
        # can't delete if not authenticated
        response = self.client.delete(url)
        assert response.status_code == 401
        assert Preview.objects.filter(id=preview.id)

        # can't delete if not your add-on
        self.client.login_api(user_factory())
        response = self.client.delete(url)
        assert response.status_code == 403

        self.client.login_api(self.user)
        response = self.client.delete(url)
        assert response.status_code == 204
        assert not Preview.objects.filter(id=preview.id)
        alog = ActivityLog.objects.get()
        assert alog.user == self.user
        assert alog.action == amo.LOG.CHANGE_MEDIA.id
        assert alog.addonlog_set.get().addon == self.addon


class TestAddonAuthorViewSet(TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        self.user = user_factory(read_dev_agreement=self.days_ago(0))
        self.addon = addon_factory(users=(self.user,))
        self.addonuser = self.addon.addonuser_set.get()
        self.detail_url = reverse_ns(
            'addon-author-detail',
            kwargs={'addon_pk': self.addon.pk, 'user_id': self.user.id},
            api_version='v5',
        )

    def test_list(self):
        list_url = reverse_ns(
            'addon-author-list', kwargs={'addon_pk': self.addon.pk}, api_version='v5'
        )
        dev_author = AddonUser.objects.create(
            addon=self.addon, user=user_factory(), role=amo.AUTHOR_ROLE_DEV, position=2
        )
        # this author shouldn't be in the results because it's deleted.
        AddonUser.objects.create(
            addon=self.addon, user=user_factory(), role=amo.AUTHOR_ROLE_DELETED
        )
        hidden_author = AddonUser.objects.create(
            addon=self.addon, user=user_factory(), listed=False, position=1
        )

        assert self.client.get(list_url).status_code == 401

        self.client.login_api(user_factory())
        assert self.client.get(list_url).status_code == 403

        self.client.login_api(self.user)
        response = self.client.get(list_url)
        assert response.status_code == 200, response.content
        assert len(response.data) == 3
        assert response.data[0] == AddonAuthorSerializer().to_representation(
            instance=self.addonuser
        )
        assert response.data[1] == AddonAuthorSerializer().to_representation(
            instance=hidden_author
        )
        assert response.data[2] == AddonAuthorSerializer().to_representation(
            instance=dev_author
        )

    def test_detail(self):
        assert self.client.get(self.detail_url).status_code == 401

        self.client.login_api(user_factory())
        assert self.client.get(self.detail_url).status_code == 403

        self.client.login_api(self.user)
        response = self.client.get(self.detail_url)
        assert response.status_code == 200, response.content
        assert response.data == AddonAuthorSerializer().to_representation(
            instance=self.addonuser
        )

    def test_developer_role(self):
        self.addonuser.update(role=amo.AUTHOR_ROLE_DEV)
        # edge-case: user is an owner of a *different* add-on too
        addon_factory(users=(self.user,))
        self.client.login_api(self.user)
        # developer role authors should be able to view all details of authors
        response = self.client.get(self.detail_url)
        assert response.status_code == 200, response.content
        assert response.data == AddonAuthorSerializer().to_representation(
            instance=self.addonuser
        )
        # but not update
        response = self.client.patch(self.detail_url, {'position': 2})
        assert response.status_code == 403, response.content

        # and not delete either
        response = self.client.delete(self.detail_url)
        assert response.status_code == 403, response.content

    def test_update(self):
        data = {'position': 2}
        assert self.client.patch(self.detail_url, data).status_code == 401

        self.client.login_api(user_factory())
        assert self.client.patch(self.detail_url, data).status_code == 403

        self.client.login_api(self.user)
        response = self.client.patch(self.detail_url, data)
        assert response.status_code == 200, response.content
        self.addonuser.reload()
        assert response.data['position'] == self.addonuser.position == 2
        assert not ActivityLog.objects.filter(
            action=amo.LOG.CHANGE_USER_WITH_ROLE.id
        ).exists()
        assert len(mail.outbox) == 0

    def test_update_role(self):
        new_author = AddonUser.objects.create(
            addon=self.addon, user=user_factory(), role=amo.AUTHOR_ROLE_DEV
        )
        self.client.login_api(self.user)
        response = self.client.patch(self.detail_url, {'role': 'developer'})
        assert response.status_code == 400, response.content
        assert response.data['role'] == ['Add-ons need at least one owner.']

        new_author.update(role=amo.AUTHOR_ROLE_OWNER)
        response = self.client.patch(self.detail_url, {'role': 'developer'})
        assert response.status_code == 200, response.content
        self.addonuser.reload()
        assert response.data['role'] == 'developer'
        assert self.addonuser.role == amo.AUTHOR_ROLE_DEV

        log = ActivityLog.objects.get(action=amo.LOG.CHANGE_USER_WITH_ROLE.id)
        assert log.user == self.user
        assert len(mail.outbox) == 1
        assert Counter(mail.outbox[0].recipients()) == Counter(
            (self.user.email, new_author.user.email)
        )

    def test_update_listed(self):
        new_author = AddonUser.objects.create(
            addon=self.addon, user=user_factory(), listed=False
        )
        self.client.login_api(self.user)
        response = self.client.patch(self.detail_url, {'listed': False})
        assert response.status_code == 400, response.content
        assert response.data['listed'] == ['Add-ons need at least one listed author.']

        new_author.update(listed=True)
        response = self.client.patch(self.detail_url, {'listed': False})
        assert response.status_code == 200, response.content
        self.addonuser.reload()
        assert response.data['listed'] is False
        assert self.addonuser.listed is False
        assert not ActivityLog.objects.filter(
            action=amo.LOG.CHANGE_USER_WITH_ROLE.id
        ).exists()
        assert len(mail.outbox) == 0

    def test_delete(self):
        new_author = AddonUser.objects.create(
            addon=self.addon,
            user=user_factory(),
            role=amo.AUTHOR_ROLE_DEV,
            listed=False,
        )
        assert self.client.delete(self.detail_url).status_code == 401

        self.client.login_api(user_factory())
        assert self.client.delete(self.detail_url).status_code == 403

        self.client.login_api(self.user)
        response = self.client.delete(self.detail_url)
        assert response.status_code == 400
        assert response.data == ['Add-ons need at least one owner.']

        new_author.update(role=amo.AUTHOR_ROLE_OWNER)
        response = self.client.delete(self.detail_url)
        assert response.status_code == 400
        assert response.data == ['Add-ons need at least one listed author.']

        new_author.update(listed=True)
        response = self.client.delete(self.detail_url)
        assert response.status_code == 204

        log = ActivityLog.objects.get(action=amo.LOG.REMOVE_USER_WITH_ROLE.id)
        assert log.user == self.user
        assert len(mail.outbox) == 1
        assert Counter(mail.outbox[0].recipients()) == Counter(
            (self.user.email, new_author.user.email)
        )


class TestAddonPendingAuthorViewSet(TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        self.user = user_factory(read_dev_agreement=self.days_ago(0))
        self.addon = addon_factory(users=(self.user,))
        self.pending_author = AddonUserPendingConfirmation.objects.create(
            addon=self.addon, user=user_factory(), role=amo.AUTHOR_ROLE_OWNER
        )
        self.detail_url = reverse_ns(
            'addon-pending-author-detail',
            kwargs={'addon_pk': self.addon.pk, 'user_id': self.pending_author.user.id},
            api_version='v5',
        )
        self.list_url = reverse_ns(
            'addon-pending-author-list',
            kwargs={'addon_pk': self.addon.pk},
            api_version='v5',
        )

    def test_list(self):
        dev_author = AddonUserPendingConfirmation.objects.create(
            addon=self.addon, user=user_factory(), role=amo.AUTHOR_ROLE_DEV
        )
        hidden_author = AddonUserPendingConfirmation.objects.create(
            addon=self.addon, user=user_factory(), listed=False
        )

        assert self.client.get(self.list_url).status_code == 401

        self.client.login_api(user_factory())
        assert self.client.get(self.list_url).status_code == 403

        self.client.login_api(self.pending_author.user)
        assert self.client.get(self.list_url).status_code == 403

        self.client.login_api(self.user)
        response = self.client.get(self.list_url)
        assert response.status_code == 200, response.content
        assert len(response.data) == 3, response.data
        assert response.data[0] == AddonPendingAuthorSerializer().to_representation(
            instance=self.pending_author
        )
        assert response.data[1] == AddonPendingAuthorSerializer().to_representation(
            instance=dev_author
        )
        assert response.data[2] == AddonPendingAuthorSerializer().to_representation(
            instance=hidden_author
        )

    def test_detail(self):
        assert self.client.get(self.detail_url).status_code == 401

        self.client.login_api(user_factory())
        assert self.client.get(self.detail_url).status_code == 403

        self.client.login_api(self.pending_author.user)
        assert self.client.get(self.detail_url).status_code == 403

        self.client.login_api(self.user)
        response = self.client.get(self.detail_url)
        assert response.status_code == 200, response.content
        assert response.data == AddonPendingAuthorSerializer().to_representation(
            instance=self.pending_author
        )

    def test_delete(self):
        assert self.client.delete(self.detail_url).status_code == 401

        self.client.login_api(user_factory())
        assert self.client.delete(self.detail_url).status_code == 403

        self.client.login_api(self.pending_author.user)
        assert self.client.get(self.detail_url).status_code == 403

        self.client.login_api(self.user)
        response = self.client.delete(self.detail_url)
        assert response.status_code == 204
        assert not AddonUserPendingConfirmation.objects.exists()

        log = ActivityLog.objects.get(action=amo.LOG.REMOVE_USER_WITH_ROLE.id)
        assert log.user == self.user
        assert len(mail.outbox) == 1
        assert Counter(mail.outbox[0].recipients()) == Counter(
            (self.user.email, self.pending_author.user.email)
        )

    def test_create(self):
        # This will be user that will be created
        new_user = user_factory(display_name='new_guy')
        data = {'user_id': new_user.id, 'role': 'developer'}
        assert self.client.post(self.list_url, data=data).status_code == 401

        self.client.login_api(user_factory())
        assert self.client.post(self.list_url, data=data).status_code == 403

        self.client.login_api(self.user)
        response = self.client.post(self.list_url, data=data)
        assert response.status_code == 201, response.content
        assert AddonUserPendingConfirmation.objects.filter(
            user=new_user, addon=self.addon, role=amo.AUTHOR_ROLE_DEV
        ).exists()

        log = ActivityLog.objects.get(action=amo.LOG.ADD_USER_WITH_ROLE.id)
        assert log.user == self.user
        assert len(mail.outbox) == 2
        assert mail.outbox[0].recipients() == [self.user.email]
        assert mail.outbox[1].recipients() == [new_user.email]

    @override_settings(API_THROTTLING=False)
    def test_create_validation(self):
        self.client.login_api(self.user)

        # user doesn't exist
        response = self.client.post(self.list_url, data={'user_id': 12345})
        assert response.status_code == 400, response.content
        assert response.data == {'user_id': ['Account not found.']}

        # not allowed
        user = user_factory(email='foo@baa.com')
        EmailUserRestriction.objects.create(email_pattern='*@baa.com')
        response = self.client.post(self.list_url, data={'user_id': user.id})
        assert response.status_code == 400, response.content
        assert response.data == {
            'user_id': [
                'The email address used for your account is not allowed for '
                'submissions.'
            ]
        }

        # can't add a user that is already an author
        user.update(email='foo@mozilla.com')
        dupe_addonuser = AddonUser.objects.create(addon=self.addon, user=user)
        response = self.client.post(self.list_url, data={'user_id': user.id})
        assert response.status_code == 400, response.content
        assert response.data == {'user_id': ['An author can only be present once.']}

        dupe_addonuser.delete()
        # can't add the same pending author twice
        response = self.client.post(
            self.list_url, data={'user_id': self.pending_author.user.id}
        )
        assert response.status_code == 400, response.content
        assert response.data == {'user_id': ['An author can only be present once.']}

        # account needs a display name
        assert not user.display_name
        response = self.client.post(self.list_url, data={'user_id': user.id})
        assert response.status_code == 400, response.content
        assert response.data == {
            'user_id': [
                'The account needs a display name before it can be added as an author.'
            ]
        }

    def test_update_role(self):
        self.client.login_api(self.user)
        response = self.client.patch(self.detail_url, {'role': 'developer'})
        assert response.status_code == 200, response.content
        self.pending_author.reload()
        assert response.data['role'] == 'developer'
        assert self.pending_author.role == amo.AUTHOR_ROLE_DEV

        log = ActivityLog.objects.get(action=amo.LOG.CHANGE_USER_WITH_ROLE.id)
        assert log.user == self.user
        assert len(mail.outbox) == 1
        assert Counter(mail.outbox[0].recipients()) == Counter(
            (self.user.email, self.pending_author.user.email)
        )

    def test_confirm(self):
        AddonUser.objects.create(addon=self.addon, user=user_factory(), position=3)
        confirm_url = reverse_ns(
            'addon-pending-author-confirm',
            kwargs={'addon_pk': self.addon.pk},
            api_version='v5',
        )

        assert self.client.post(confirm_url).status_code == 401

        self.client.login_api(user_factory())  # random user can't confirm, only invited
        assert self.client.post(confirm_url).status_code == 403

        pending_user = self.pending_author.user
        assert pending_user not in self.addon.reload().authors.all()
        self.client.login_api(pending_user)
        response = self.client.post(confirm_url)
        assert response.status_code == 200

        assert pending_user in self.addon.reload().authors.all()
        assert not AddonUserPendingConfirmation.objects.filter(
            id=self.pending_author.id
        ).exists()
        addonuser = AddonUser.objects.get(addon=self.addon, user=pending_user)
        assert addonuser.position == 4  # should be + 1 after the existing authors
        assert addonuser.role == self.pending_author.role
        assert addonuser.listed == self.pending_author.listed

    def test_decline(self):
        decline_url = reverse_ns(
            'addon-pending-author-decline',
            kwargs={'addon_pk': self.addon.pk},
            api_version='v5',
        )

        assert self.client.post(decline_url).status_code == 401

        self.client.login_api(user_factory())  # random user can't decline, only invited
        assert self.client.post(decline_url).status_code == 403

        pending_user = self.pending_author.user
        self.client.login_api(pending_user)
        response = self.client.post(decline_url)
        assert response.status_code == 200

        assert not AddonUserPendingConfirmation.objects.filter(
            id=self.pending_author.id
        ).exists()
        assert pending_user not in self.addon.reload().authors.all()

    def test_developer_role(self):
        AddonUser.objects.get(user=self.user).update(role=amo.AUTHOR_ROLE_DEV)
        # edge-case: user is an owner of a *different* add-on too
        addon_factory(users=(self.user,))
        self.client.login_api(self.user)

        # developer role authors should be able to view all details of authors
        response = self.client.get(self.detail_url)
        assert response.status_code == 200, response.content
        assert response.data == AddonPendingAuthorSerializer().to_representation(
            instance=self.pending_author
        )
        # but not update
        response = self.client.patch(self.detail_url, {'role': 'owner'})
        assert response.status_code == 403, response.content

        # or create
        response = self.client.post(
            self.list_url,
            data={'user_id': user_factory(display_name='me!').id, 'role': 'owner'},
        )
        assert response.status_code == 403, response.content

        # and not delete either
        response = self.client.delete(self.detail_url)
        assert response.status_code == 403, response.content


class TestBrowserMapping(TestCase):
    def setUp(self):
        super().setUp()

        self.url = reverse_ns('addon-browser-mappings', api_version='v5')

    def assert_json_results(self, response, expected_results):
        json = response.json()
        assert 'results' in json
        assert 'count' in json
        assert 'page_size' in json
        assert json['count'] == expected_results
        assert json['page_size'] == 100  # We use `LargePageNumberPagination`.
        return json['results']

    def test_invalid_params(self):
        for query_string in ['', '?invalid=param', '?browser=not-a-browser']:
            res = self.client.get(f'{self.url}{query_string}')
            assert res.status_code == 400
            assert res['cache-control'] == 's-maxage=0'
            assert res.json() == {'detail': 'Invalid browser parameter'}

    def test_get(self):
        addon_1 = addon_factory()
        extension_id_1 = 'an-extension-id'
        AddonBrowserMapping.objects.create(
            addon=addon_1,
            extension_id=extension_id_1,
            browser=CHROME,
        )
        addon_2 = addon_factory()
        extension_id_2 = 'another-extension-id'
        AddonBrowserMapping.objects.create(
            addon=addon_2,
            extension_id=extension_id_2,
            browser=CHROME,
        )
        # Shouldn't show up because of the add-on status.
        AddonBrowserMapping.objects.create(
            addon=addon_factory(status=amo.STATUS_NOMINATED),
            extension_id='some-other-extension-id-1',
            browser=CHROME,
        )
        # Shouldn't show up because the browser is unrelated.
        AddonBrowserMapping.objects.create(
            addon=addon_1,
            extension_id='some-other-extension-id-2',
            browser=0,
        )
        # Shouldn't show up because the add-on has been disabled by the user.
        AddonBrowserMapping.objects.create(
            addon=addon_factory(disabled_by_user=True),
            extension_id='some-other-extension-id-3',
            browser=CHROME,
        )
        # - 1 for counting the number of results
        # - 1 for fetching the results of the first (and only) page
        with self.assertNumQueries(2):
            res = self.client.get(f'{self.url}?browser=chrome')

        assert res.status_code == 200
        assert res['cache-control'] == 'max-age=86400'

        results = self.assert_json_results(res, 2)
        assert results[0] == {
            'extension_id': extension_id_1,
            'addon_guid': addon_1.guid,
        }
        assert results[1] == {
            'extension_id': extension_id_2,
            'addon_guid': addon_2.guid,
        }
