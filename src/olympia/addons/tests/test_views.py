# -*- coding: utf-8 -*-
import json

from unittest import mock

from django.test.utils import override_settings
from django.utils.encoding import force_bytes, force_text
from django.utils.http import urlsafe_base64_encode, urlunquote

import pytest

from elasticsearch import Elasticsearch
from unittest.mock import patch
from rest_framework.test import APIRequestFactory
from waffle import switch_is_active

from olympia import amo
from olympia.addons.models import Addon, AddonUser, Category, ReplacementAddon
from olympia.addons.utils import generate_addon_guid
from olympia.addons.views import (
    DEFAULT_FIND_REPLACEMENT_PATH, FIND_REPLACEMENT_SRC,
    AddonAutoCompleteSearchView, AddonSearchView)
from olympia.amo.tests import (
    APITestClient, ESTestCase, TestCase, addon_factory, collection_factory,
    reverse_ns, user_factory, version_factory)
from olympia.amo.urlresolvers import get_outgoing_url, reverse
from olympia.bandwagon.models import CollectionAddon
from olympia.constants.categories import CATEGORIES, CATEGORIES_BY_ID
from olympia.discovery.models import DiscoveryItem
from olympia.users.models import UserProfile
from olympia.versions.models import ApplicationsVersions, AppVersion


class TestStatus(TestCase):
    client_class = APITestClient
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestStatus, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version
        self.file = self.version.all_files[0]
        assert self.addon.status == amo.STATUS_APPROVED
        self.url = reverse_ns(
            'addon-detail', api_version='v5', kwargs={'pk': self.addon.pk})

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
            DEFAULT_FIND_REPLACEMENT_PATH + '?src=%s' % FIND_REPLACEMENT_SRC)

    def test_match(self):
        addon_factory(slug='replacey')
        ReplacementAddon.objects.create(guid='xxx', path='/addon/replacey/')
        self.url = reverse('addons.find_replacement') + '?guid=xxx'
        response = self.client.get(self.url)
        self.assert3xx(
            response, '/addon/replacey/?src=%s' % FIND_REPLACEMENT_SRC)

    def test_match_no_leading_slash(self):
        addon_factory(slug='replacey')
        ReplacementAddon.objects.create(guid='xxx', path='addon/replacey/')
        self.url = reverse('addons.find_replacement') + '?guid=xxx'
        response = self.client.get(self.url)
        self.assert3xx(
            response, '/addon/replacey/?src=%s' % FIND_REPLACEMENT_SRC)

    def test_no_guid_param_is_404(self):
        self.url = reverse('addons.find_replacement')
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_external_url(self):
        ReplacementAddon.objects.create(
            guid='xxx', path='https://mozilla.org/')
        self.url = reverse('addons.find_replacement') + '?guid=xxx'
        response = self.client.get(self.url)
        self.assert3xx(
            response, get_outgoing_url('https://mozilla.org/'))


class AddonAndVersionViewSetDetailMixin(object):
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
        data = json.loads(force_text(response.content))
        assert data['detail'] == (
            'Authentication credentials were not provided.')
        assert data['is_disabled_by_developer'] is False
        assert data['is_disabled_by_mozilla'] is False

    def test_get_not_public_no_rights(self):
        self.addon.update(status=amo.STATUS_NOMINATED)
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403
        data = json.loads(force_text(response.content))
        assert data['detail'] == (
            'You do not have permission to perform this action.')
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
        data = json.loads(force_text(response.content))
        assert data['detail'] == (
            'Authentication credentials were not provided.')
        assert data['is_disabled_by_developer'] is True
        assert data['is_disabled_by_mozilla'] is False

    def test_get_disabled_by_user_other_user(self):
        self.addon.update(disabled_by_user=True)
        user = UserProfile.objects.create(username='someone')
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403
        data = json.loads(force_text(response.content))
        assert data['detail'] == (
            'You do not have permission to perform this action.')
        assert data['is_disabled_by_developer'] is True
        assert data['is_disabled_by_mozilla'] is False

    def test_disabled_by_admin_anonymous(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        response = self.client.get(self.url)
        assert response.status_code == 401
        data = json.loads(force_text(response.content))
        assert data['detail'] == (
            'Authentication credentials were not provided.')
        assert data['is_disabled_by_developer'] is False
        assert data['is_disabled_by_mozilla'] is True

    def test_disabled_by_admin_no_rights(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        user = UserProfile.objects.create(username='someone')
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403
        data = json.loads(force_text(response.content))
        assert data['detail'] == (
            'You do not have permission to perform this action.')
        assert data['is_disabled_by_developer'] is False
        assert data['is_disabled_by_mozilla'] is True

    def test_get_not_listed(self):
        self.make_addon_unlisted(self.addon)
        response = self.client.get(self.url)
        assert response.status_code == 401
        data = json.loads(force_text(response.content))
        assert data['detail'] == (
            'Authentication credentials were not provided.')
        assert data['is_disabled_by_developer'] is False
        assert data['is_disabled_by_mozilla'] is False

    def test_get_not_listed_no_rights(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.make_addon_unlisted(self.addon)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403
        data = json.loads(force_text(response.content))
        assert data['detail'] == (
            'You do not have permission to perform this action.')
        assert data['is_disabled_by_developer'] is False
        assert data['is_disabled_by_mozilla'] is False

    def test_get_not_listed_simple_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.make_addon_unlisted(self.addon)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403
        data = json.loads(force_text(response.content))
        assert data['detail'] == (
            'You do not have permission to perform this action.')
        assert data['is_disabled_by_developer'] is False
        assert data['is_disabled_by_mozilla'] is False

    def test_get_not_listed_specific_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
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
        data = json.loads(force_text(response.content))
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
        data = json.loads(force_text(response.content))
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
        data = json.loads(force_text(response.content))
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
        data = json.loads(force_text(response.content))
        assert data['detail'] == 'Not found.'
        # `is_disabled_by_developer` and `is_disabled_by_mozilla` are only
        # added for 401/403.
        assert 'is_disabled_by_developer' not in data
        assert 'is_disabled_by_mozilla' not in data

    def test_get_addon_not_found(self):
        self._set_tested_url(self.addon.pk + 42)
        response = self.client.get(self.url)
        assert response.status_code == 404
        data = json.loads(force_text(response.content))
        assert data['detail'] == 'Not found.'
        # `is_disabled_by_developer` and `is_disabled_by_mozilla` are only
        # added for 401/403.
        assert 'is_disabled_by_developer' not in data
        assert 'is_disabled_by_mozilla' not in data


class TestAddonViewSetDetail(AddonAndVersionViewSetDetailMixin, TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestAddonViewSetDetail, self).setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')
        self._set_tested_url(self.addon.pk)

    def _test_url(self, **kwargs):
        response = self.client.get(self.url, data=kwargs)
        assert response.status_code == 200
        result = json.loads(force_text(response.content))
        assert result['id'] == self.addon.pk
        assert result['name'] == {'en-US': u'My Addôn'}
        assert result['slug'] == self.addon.slug
        assert result['last_updated'] == (
            self.addon.last_updated.replace(microsecond=0).isoformat() + 'Z')
        return result

    def _set_tested_url(self, param):
        self.url = reverse_ns(
            'addon-detail', api_version='v5', kwargs={'pk': param})

    def test_queries(self):
        with self.assertNumQueries(15):
            # 15 queries
            # - 2 savepoints because of tests
            # - 1 for the add-on
            # - 1 for its translations
            # - 1 for its categories
            # - 1 for its current_version
            # - 1 for translations of that version
            # - 1 for applications versions of that version
            # - 1 for files of that version
            # - 1 for authors
            # - 1 for previews
            # - 1 for license
            # - 1 for translations of the license
            # - 1 for discovery item (is_recommended)
            # - 1 for tags
            self._test_url(lang='en-US')

    def test_detail_url_with_reviewers_in_the_url(self):
        self.addon.update(slug='something-reviewers')
        self.url = reverse_ns('addon-detail', kwargs={'pk': self.addon.slug})
        self._test_url()

    def test_hide_latest_unlisted_version_anonymous(self):
        unlisted_version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        unlisted_version.update(created=self.days_ago(1))
        result = self._test_url()
        assert 'latest_unlisted_version' not in result

    def test_hide_latest_unlisted_version_simple_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        unlisted_version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        unlisted_version.update(created=self.days_ago(1))
        result = self._test_url()
        assert 'latest_unlisted_version' not in result

    def test_show_latest_unlisted_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)

        unlisted_version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        unlisted_version.update(created=self.days_ago(1))
        result = self._test_url()
        assert result['latest_unlisted_version']
        assert result['latest_unlisted_version']['id'] == unlisted_version.pk

    def test_show_latest_unlisted_version_unlisted_reviewer(self):
        user = UserProfile.objects.create(username='author')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.client.login_api(user)

        unlisted_version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        unlisted_version.update(created=self.days_ago(1))
        result = self._test_url()
        assert result['latest_unlisted_version']
        assert result['latest_unlisted_version']['id'] == unlisted_version.pk

    def test_with_lang(self):
        self.addon.name = {
            'en-US': u'My Addôn, mine',
            'fr': u'Mon Addôn, le mien',
        }
        self.addon.save()

        response = self.client.get(self.url, {'lang': 'en-US'})
        assert response.status_code == 200
        result = json.loads(force_text(response.content))
        assert result['id'] == self.addon.pk
        assert result['name'] == {'en-US': u'My Addôn, mine'}

        response = self.client.get(self.url, {'lang': 'fr'})
        assert response.status_code == 200
        result = json.loads(force_text(response.content))
        assert result['id'] == self.addon.pk
        assert result['name'] == {'fr': u'Mon Addôn, le mien'}

        response = self.client.get(self.url, {'lang': 'de'})
        assert response.status_code == 200
        result = json.loads(force_text(response.content))
        assert result['id'] == self.addon.pk
        assert result['name'] == {'en-US': u'My Addôn, mine'}

        overridden_api_gates = {
            'v5': ('l10n_flat_input_output',)}
        with override_settings(DRF_API_GATES=overridden_api_gates):
            response = self.client.get(self.url, {'lang': 'en-US'})
            assert response.status_code == 200
            result = json.loads(force_text(response.content))
            assert result['id'] == self.addon.pk
            assert result['name'] == u'My Addôn, mine'

            response = self.client.get(self.url, {'lang': 'fr'})
            assert response.status_code == 200
            result = json.loads(force_text(response.content))
            assert result['id'] == self.addon.pk
            assert result['name'] == u'Mon Addôn, le mien'

            response = self.client.get(self.url, {'lang': 'de'})
            assert response.status_code == 200
            result = json.loads(force_text(response.content))
            assert result['id'] == self.addon.pk
            assert result['name'] == u'My Addôn, mine'

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
        data = json.loads(force_text(response.content))
        assert data == {'detail': 'Invalid "app" parameter.'}

        # Invalid appversion
        response = self.client.get(
            self.url, {'appversion': 'fr', 'app': 'firefox'})
        assert response.status_code == 400
        data = json.loads(force_text(response.content))
        assert data == {'detail': 'Invalid "appversion" parameter.'}

        # Invalid app
        response = self.client.get(
            self.url, {'appversion': '58.0', 'app': 'fr'})
        assert response.status_code == 400
        data = json.loads(force_text(response.content))
        assert data == {'detail': 'Invalid "app" parameter.'}


class TestVersionViewSetDetail(AddonAndVersionViewSetDetailMixin, TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestVersionViewSetDetail, self).setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')

        # Don't use addon.current_version, changing its state as we do in
        # the tests might render the add-on itself inaccessible.
        self.version = version_factory(addon=self.addon)
        self._set_tested_url(self.addon.pk)

    def _test_url(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(force_text(response.content))
        assert result['id'] == self.version.pk
        assert result['version'] == self.version.version

    def _set_tested_url(self, param):
        self.url = reverse_ns('addon-version-detail', kwargs={
            'addon_pk': param, 'pk': self.version.pk})

    def test_version_get_not_found(self):
        self.url = reverse_ns('addon-version-detail', kwargs={
            'addon_pk': self.addon.pk, 'pk': self.version.pk + 42})
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_disabled_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url()

    def test_disabled_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url()

    def test_disabled_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url()

    def test_disabled_version_anonymous(self):
        self.version.files.update(status=amo.STATUS_DISABLED)
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_disabled_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
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
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_unlisted_version_unlisted_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.client.login_api(user)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self._test_url()

    def test_unlisted_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self._test_url()

    def test_unlisted_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self._test_url()

    def test_unlisted_version_anonymous(self):
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_unlisted_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        assert response.status_code == 403


class TestVersionViewSetList(AddonAndVersionViewSetDetailMixin, TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestVersionViewSetList, self).setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')
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
            addon=self.addon, version='42.0',
            channel=amo.RELEASE_CHANNEL_UNLISTED)

        self._set_tested_url(self.addon.pk)

    def _test_url(self, **kwargs):
        response = self.client.get(self.url, data=kwargs)
        assert response.status_code == 200
        result = json.loads(force_text(response.content))
        assert result['results']
        assert len(result['results']) == 2
        result_version = result['results'][0]
        assert result_version['id'] == self.version.pk
        assert result_version['version'] == self.version.version
        result_version = result['results'][1]
        assert result_version['id'] == self.old_version.pk
        assert result_version['version'] == self.old_version.version

    def _test_url_contains_all(self, **kwargs):
        response = self.client.get(self.url, data=kwargs)
        assert response.status_code == 200
        result = json.loads(force_text(response.content))
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
        result = json.loads(force_text(response.content))
        assert result['results']
        assert len(result['results']) == 1
        result_version = result['results'][0]
        assert result_version['id'] == self.old_version.pk
        assert result_version['version'] == self.old_version.version

    def _set_tested_url(self, param):
        self.url = reverse_ns('addon-version-list', kwargs={'addon_pk': param})

    def test_queries(self):
        with self.assertNumQueries(13):
            # 13 queries:
            # - 2 savepoints because of tests
            # - 2 user and its groups
            # - 2 addon and its translations
            # - 1 count for pagination
            # - 1 versions themselves
            # - 1 translations (release notes)
            # - 1 applications versions
            # - 1 files
            # - 1 licenses
            # - 1 licenses translations
            self._test_url(lang='en-US')

    def test_bad_filter(self):
        response = self.client.get(self.url, data={'filter': 'ahahaha'})
        assert response.status_code == 400
        data = json.loads(force_text(response.content))
        assert data == ['Invalid "filter" parameter specified.']

    def test_disabled_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url_only_contains_old_version()

        # A reviewer can see disabled versions when explicitly asking for them.
        self._test_url(filter='all_without_unlisted')

    def test_disabled_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url_only_contains_old_version()

        # An author can see disabled versions when explicitly asking for them.
        self._test_url(filter='all_without_unlisted')

    def test_disabled_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url_only_contains_old_version()

        # An admin can see disabled versions when explicitly asking for them.
        self._test_url(filter='all_without_unlisted')

    def test_disabled_version_anonymous(self):
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url_only_contains_old_version()
        response = self.client.get(
            self.url, data={'filter': 'all_without_unlisted'})
        assert response.status_code == 401
        response = self.client.get(
            self.url, data={'filter': 'all_with_deleted'})
        assert response.status_code == 401

    def test_disabled_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url_only_contains_old_version()
        response = self.client.get(
            self.url, data={'filter': 'all_without_unlisted'})
        assert response.status_code == 403
        response = self.client.get(
            self.url, data={'filter': 'all_with_deleted'})
        assert response.status_code == 403

    def test_deleted_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.delete()
        self._test_url_only_contains_old_version()
        self._test_url_only_contains_old_version(filter='all_without_unlisted')
        response = self.client.get(
            self.url, data={'filter': 'all_with_deleted'})
        assert response.status_code == 403
        response = self.client.get(
            self.url, data={'filter': 'all_with_unlisted'})
        assert response.status_code == 403

    def test_deleted_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        self.version.delete()
        self._test_url_only_contains_old_version()
        self._test_url_only_contains_old_version(filter='all_without_unlisted')
        response = self.client.get(
            self.url, data={'filter': 'all_with_deleted'})
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

        self._test_url_contains_all(filter='all_with_unlisted')

    def test_with_unlisted_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)

        self._test_url_contains_all(filter='all_with_unlisted')

    def test_deleted_version_anonymous(self):
        self.version.delete()
        self._test_url_only_contains_old_version()

        response = self.client.get(
            self.url, data={'filter': 'all_with_deleted'})
        assert response.status_code == 401

    def test_all_without_and_with_unlisted_anonymous(self):
        response = self.client.get(
            self.url, data={'filter': 'all_without_unlisted'})
        assert response.status_code == 401
        response = self.client.get(
            self.url, data={'filter': 'all_with_unlisted'})
        assert response.status_code == 401

    def test_deleted_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.delete()
        self._test_url_only_contains_old_version()

        response = self.client.get(
            self.url, data={'filter': 'all_with_deleted'})
        assert response.status_code == 403

    def test_all_without_and_with_unlisted_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.delete()
        response = self.client.get(
            self.url, data={'filter': 'all_without_unlisted'})
        assert response.status_code == 403
        response = self.client.get(
            self.url, data={'filter': 'all_with_unlisted'})
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
        response = self.client.get(
            self.url, data={'filter': 'all_with_unlisted'})
        assert response.status_code == 200
        result = json.loads(force_text(response.content))
        assert result['results']
        assert len(result['results']) == 1
        result_version = result['results'][0]
        assert result_version['id'] == self.unlisted_version.pk
        assert result_version['version'] == self.unlisted_version.version

        # And that without_unlisted doesn't fail when there are no unlisted
        response = self.client.get(
            self.url, data={'filter': 'all_without_unlisted'})
        assert response.status_code == 200
        result = json.loads(force_text(response.content))
        assert result['results'] == []


class TestAddonViewSetEulaPolicy(TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestAddonViewSetEulaPolicy, self).setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')
        self.url = reverse_ns(
            'addon-eula-policy', kwargs={'pk': self.addon.pk})

    def test_url(self):
        self.detail_url = reverse_ns(
            'addon-detail', kwargs={'pk': self.addon.pk})
        assert self.url == '%s%s' % (self.detail_url, 'eula_policy/')

    def test_disabled_anonymous(self):
        self.addon.update(disabled_by_user=True)
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_policy_none(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(force_text(response.content))
        assert data['eula'] is None
        assert data['privacy_policy'] is None

    def test_policy(self):
        self.addon.eula = {'en-US': u'My Addôn EULA', 'fr': u'Hoüla'}
        self.addon.privacy_policy = u'My Prïvacy, My Policy'
        self.addon.save()
        response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(force_text(response.content))
        assert data['eula'] == {'en-US': u'My Addôn EULA', 'fr': u'Hoüla'}
        assert data['privacy_policy'] == {'en-US': u'My Prïvacy, My Policy'}


class TestAddonSearchView(ESTestCase):
    client_class = APITestClient

    fixtures = ['base/users']

    def setUp(self):
        super(TestAddonSearchView, self).setUp()
        self.url = reverse_ns('addon-search')
        self.create_switch('return-to-amo', active=True)
        switch_is_active('return-to-amo')

    def tearDown(self):
        super(TestAddonSearchView, self).tearDown()
        self.empty_index('default')
        self.refresh()

    def test_get_queryset_excludes(self):
        addon_factory(slug='my-addon', name=u'My Addôn', popularity=666)
        addon_factory(slug='my-second-addon', name=u'My second Addôn',
                      popularity=555)
        self.refresh()

        view = AddonSearchView()
        view.request = APIRequestFactory().get('/')
        qset = view.get_queryset()

        assert set(qset.to_dict()['_source']['excludes']) == set(
            ('*.raw', 'boost', 'colors', 'hotness', 'name', 'description',
             'name_l10n_*', 'description_l10n_*', 'summary', 'summary_l10n_*')
        )

        response = qset.execute()

        source_keys = response.hits.hits[0]['_source'].keys()

        assert not any(key in source_keys for key in (
            'boost', 'description', 'hotness', 'name', 'summary',
        ))

        assert not any(
            key.startswith('name_l10n_') for key in source_keys
        )

        assert not any(
            key.startswith('description_l10n_') for key in source_keys
        )

        assert not any(
            key.startswith('summary_l10n_') for key in source_keys
        )

        assert not any(
            key.endswith('.raw') for key in source_keys
        )

    def perform_search(self, url, data=None, expected_status=200,
                       expected_queries=0, **headers):
        with self.assertNumQueries(expected_queries):
            response = self.client.get(url, data, **headers)
        assert response.status_code == expected_status, response.content
        data = json.loads(force_text(response.content))
        return data

    def test_basic(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              popularity=666)
        addon2 = addon_factory(slug='my-second-addon', name=u'My second Addôn',
                               popularity=555)
        self.refresh()

        data = self.perform_search(self.url)  # No query.
        assert data['count'] == 2
        assert len(data['results']) == 2

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['name'] == {'en-US': u'My Addôn'}
        assert result['slug'] == 'my-addon'
        assert result['last_updated'] == (
            addon.last_updated.replace(microsecond=0).isoformat() + 'Z')

        # latest_unlisted_version should never be exposed in public search.
        assert 'latest_unlisted_version' not in result

        result = data['results'][1]
        assert result['id'] == addon2.pk
        assert result['name'] == {'en-US': u'My second Addôn'}
        assert result['slug'] == 'my-second-addon'

        # latest_unlisted_version should never be exposed in public search.
        assert 'latest_unlisted_version' not in result

    def test_empty(self):
        data = self.perform_search(self.url)
        assert data['count'] == 0
        assert len(data['results']) == 0

    def test_es_queries_made_no_results(self):
        with patch.object(
                Elasticsearch, 'search',
                wraps=amo.search.get_es().search) as search_mock:
            data = self.perform_search(self.url, data={'q': 'foo'})
            assert data['count'] == 0
            assert len(data['results']) == 0
            assert search_mock.call_count == 1

    def test_es_queries_made_some_result(self):
        addon_factory(slug='foormidable', name=u'foo')
        addon_factory(slug='foobar', name=u'foo')
        self.refresh()

        with patch.object(
                Elasticsearch, 'search',
                wraps=amo.search.get_es().search) as search_mock:
            data = self.perform_search(
                self.url, data={'q': 'foo', 'page_size': 1})
            assert data['count'] == 2
            assert len(data['results']) == 1
            assert search_mock.call_count == 1

    def test_no_unlisted(self):
        addon_factory(slug='my-addon', name=u'My Addôn',
                      status=amo.STATUS_NULL,
                      popularity=666,
                      version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED})
        self.refresh()
        data = self.perform_search(self.url)
        assert data['count'] == 0
        assert len(data['results']) == 0

    def test_pagination(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              popularity=33)
        addon2 = addon_factory(slug='my-second-addon', name=u'My second Addôn',
                               popularity=22)
        addon_factory(slug='my-third-addon', name=u'My third Addôn',
                      popularity=11)
        self.refresh()

        data = self.perform_search(self.url, {'page_size': 1})
        assert data['count'] == 3
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['name'] == {'en-US': u'My Addôn'}
        assert result['slug'] == 'my-addon'

        # Search using the second page URL given in return value.
        data = self.perform_search(data['next'])
        assert data['count'] == 3
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon2.pk
        assert result['name'] == {'en-US': u'My second Addôn'}
        assert result['slug'] == 'my-second-addon'

    def test_pagination_sort_and_query(self):
        addon_factory(slug='my-addon', name=u'Cy Addôn')
        addon2 = addon_factory(slug='my-second-addon', name=u'By second Addôn')
        addon1 = addon_factory(slug='my-first-addon', name=u'Ay first Addôn')
        addon_factory(slug='only-happy-when-itrains', name=u'Garbage')
        self.refresh()

        data = self.perform_search(self.url, {
            'page_size': 1, 'q': u'addôn', 'sort': 'name'})
        assert data['count'] == 3
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon1.pk
        assert result['name'] == {'en-US': u'Ay first Addôn'}

        # Search using the second page URL given in return value.
        assert 'sort=name' in data['next']
        data = self.perform_search(data['next'])
        assert data['count'] == 3
        assert len(data['results']) == 1
        assert 'sort=name' in data['previous']

        result = data['results'][0]
        assert result['id'] == addon2.pk
        assert result['name'] == {'en-US': u'By second Addôn'}

    def test_filtering_only_reviewed_addons(self):
        public_addon = addon_factory(slug='my-addon', name=u'My Addôn',
                                     popularity=222)
        addon_factory(slug='my-incomplete-addon', name=u'My incomplete Addôn',
                      status=amo.STATUS_NULL)
        addon_factory(slug='my-disabled-addon', name=u'My disabled Addôn',
                      status=amo.STATUS_DISABLED)
        addon_factory(slug='my-unlisted-addon', name=u'My unlisted Addôn',
                      version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED})
        addon_factory(slug='my-disabled-by-user-addon',
                      name=u'My disabled by user Addôn',
                      disabled_by_user=True)
        self.refresh()

        data = self.perform_search(self.url)
        assert data['count'] == 1
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == public_addon.pk
        assert result['name'] == {'en-US': u'My Addôn'}
        assert result['slug'] == 'my-addon'

    def test_with_query(self):
        addon = addon_factory(slug='my-addon', name=u'My Addon',
                              tags=['some_tag'])
        addon_factory(slug='unrelated', name=u'Unrelated')
        self.refresh()

        data = self.perform_search(self.url, {'q': 'addon'})
        assert data['count'] == 1
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['name'] == {'en-US': u'My Addon'}
        assert result['slug'] == 'my-addon'

    def test_with_session_cookie(self):
        # Session cookie should be ignored, therefore a request with it should
        # not cause more database queries.
        self.client.login(email='regular@mozilla.com')
        data = self.perform_search(self.url)
        assert data['count'] == 0
        assert len(data['results']) == 0

    def test_filter_by_type(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn')
        theme = addon_factory(slug='my-theme', name=u'My Thème',
                              type=amo.ADDON_STATICTHEME)
        addon_factory(slug='my-search', name=u'My Seárch',
                      type=amo.ADDON_SEARCH)
        self.refresh()

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
            slug='my-addon', name=u'Featured Addôn', recommended=True)
        addon_factory(slug='other-addon', name=u'Other Addôn')
        assert addon.is_recommended
        self.reindex(Addon)

        data = self.perform_search(self.url, {'featured': 'true'})
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == addon.pk

    def test_filter_by_recommended(self):
        addon = addon_factory(
            slug='my-addon', name=u'Recomménded Addôn', recommended=True)
        addon_factory(slug='other-addon', name=u'Other Addôn')
        assert addon.is_recommended
        self.reindex(Addon)

        data = self.perform_search(self.url, {'recommended': 'true'})
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == addon.pk

    def test_filter_by_platform(self):
        # First add-on is available for all platforms.
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              popularity=33)
        addon_factory(
            slug='my-linux-addon', name=u'My linux-only Addön',
            file_kw={'platform': amo.PLATFORM_LINUX.id},
            popularity=22)
        mac_addon = addon_factory(
            slug='my-mac-addon', name=u'My mac-only Addön',
            file_kw={'platform': amo.PLATFORM_MAC.id},
            popularity=11)
        self.refresh()

        data = self.perform_search(self.url)
        assert data['count'] == 3
        assert len(data['results']) == 3
        assert data['results'][0]['id'] == addon.pk

        data = self.perform_search(self.url, {'platform': 'mac'})
        assert data['count'] == 2
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == addon.pk
        assert data['results'][1]['id'] == mac_addon.pk

    def test_filter_by_app(self):
        addon = addon_factory(
            slug='my-addon', name=u'My Addôn', popularity=33,
            version_kw={'min_app_version': '42.0',
                        'max_app_version': '*'})
        an_addon = addon_factory(
            slug='my-tb-addon', name=u'My ANd Addøn', popularity=22,
            version_kw={'application': amo.ANDROID.id,
                        'min_app_version': '42.0',
                        'max_app_version': '*'})
        both_addon = addon_factory(
            slug='my-both-addon', name=u'My Both Addøn', popularity=11,
            version_kw={'min_app_version': '43.0',
                        'max_app_version': '*'})
        # both_addon was created with firefox compatibility, manually add
        # android, making it compatible with both.
        ApplicationsVersions.objects.create(
            application=amo.ANDROID.id, version=both_addon.current_version,
            min=AppVersion.objects.create(
                application=amo.ANDROID.id, version='43.0'),
            max=AppVersion.objects.get(
                application=amo.ANDROID.id, version='*'))
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
            slug='my-addon', name=u'My Addôn', popularity=33,
            version_kw={'min_app_version': '42.0',
                        'max_app_version': '*'})
        an_addon = addon_factory(
            slug='my-tb-addon', name=u'My ANd Addøn', popularity=22,
            version_kw={'application': amo.ANDROID.id,
                        'min_app_version': '42.0',
                        'max_app_version': '*'})
        both_addon = addon_factory(
            slug='my-both-addon', name=u'My Both Addøn', popularity=11,
            version_kw={'min_app_version': '43.0',
                        'max_app_version': '*'})
        # both_addon was created with firefox compatibility, manually add
        # android, making it compatible with both.
        ApplicationsVersions.objects.create(
            application=amo.ANDROID.id, version=both_addon.current_version,
            min=AppVersion.objects.create(
                application=amo.ANDROID.id, version='43.0'),
            max=AppVersion.objects.get(
                application=amo.ANDROID.id, version='*'))
        # Because the manually created ApplicationsVersions was created after
        # the initial save, we need to reindex and not just refresh.
        self.reindex(Addon)

        data = self.perform_search(self.url, {'app': 'firefox',
                                              'appversion': '46.0'})
        assert data['count'] == 2
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == addon.pk
        assert data['results'][1]['id'] == both_addon.pk

        data = self.perform_search(self.url, {'app': 'android',
                                              'appversion': '43.0.1'})
        assert data['count'] == 2
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == an_addon.pk
        assert data['results'][1]['id'] == both_addon.pk

        data = self.perform_search(self.url, {'app': 'firefox',
                                              'appversion': '42.0'})
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == addon.pk

        data = self.perform_search(self.url, {'app': 'android',
                                              'appversion': '42.0.1'})
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == an_addon.pk

    def test_filter_by_category(self):
        static_category = (
            CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION]['alerts-updates'])
        category = Category.from_static_category(static_category, True)
        addon = addon_factory(
            slug='my-addon', name=u'My Addôn', category=category)

        self.refresh()

        # Create an add-on in a different category.
        static_category = (
            CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION]['tabs'])
        other_category = Category.from_static_category(static_category, True)
        addon_factory(slug='different-addon', category=other_category)

        self.refresh()

        # Search for add-ons in the first category. There should be only one.
        data = self.perform_search(self.url, {'app': 'firefox',
                                              'type': 'extension',
                                              'category': category.slug})
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == addon.pk

    def test_filter_by_category_multiple_types(self):
        def get_category(type_, name):
            static_category = CATEGORIES[amo.FIREFOX.id][type_][name]
            return Category.from_static_category(static_category, True)

        addon_ext = addon_factory(
            slug='my-addon-ext', name=u'My Addôn Ext',
            category=get_category(amo.ADDON_EXTENSION, 'other'),
            type=amo.ADDON_EXTENSION)
        addon_st = addon_factory(
            slug='my-addon-st', name=u'My Addôn ST',
            category=get_category(amo.ADDON_STATICTHEME, 'other'),
            type=amo.ADDON_STATICTHEME)

        self.refresh()

        # Create some add-ons in a different category.
        addon_factory(
            slug='different-addon-ext', name=u'Diff Addôn Ext',
            category=get_category(amo.ADDON_EXTENSION, 'tabs'),
            type=amo.ADDON_EXTENSION)
        addon_factory(
            slug='different-addon-st', name=u'Diff Addôn ST',
            category=get_category(amo.ADDON_STATICTHEME, 'sports'),
            type=amo.ADDON_STATICTHEME)

        self.refresh()

        # Search for add-ons in the first category. There should be two.
        data = self.perform_search(self.url, {'app': 'firefox',
                                              'type': 'extension,statictheme',
                                              'category': 'other'})
        assert data['count'] == 2
        assert len(data['results']) == 2
        result_ids = (data['results'][0]['id'], data['results'][1]['id'])
        assert sorted(result_ids) == [addon_ext.pk, addon_st.pk]

    def test_filter_with_tags(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              tags=['some_tag'], popularity=999)
        addon2 = addon_factory(slug='another-addon', name=u'Another Addôn',
                               tags=['unique_tag', 'some_tag'],
                               popularity=333)
        addon3 = addon_factory(slug='unrelated', name=u'Unrelated',
                               tags=['unrelated'])
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
        data = self.perform_search(
            self.url, {'app': 'lol'}, expected_status=400)
        assert data == ['Invalid "app" parameter.']

    def test_filter_by_author(self):
        author = user_factory(username=u'my-fancyAuthôr')
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              tags=['some_tag'], popularity=999)
        AddonUser.objects.create(addon=addon, user=author)
        addon2 = addon_factory(slug='another-addon', name=u'Another Addôn',
                               tags=['unique_tag', 'some_tag'],
                               popularity=333)
        author2 = user_factory(username=u'my-FancyAuthôrName')
        AddonUser.objects.create(addon=addon2, user=author2)
        self.reindex(Addon)

        data = self.perform_search(self.url, {'author': u'my-fancyAuthôr'})
        assert data['count'] == 1
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['slug'] == addon.slug

    def test_filter_by_multiple_authors(self):
        author = user_factory(username='foo')
        author2 = user_factory(username='bar')
        another_author = user_factory(username='someoneelse')
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              tags=['some_tag'], popularity=999)
        AddonUser.objects.create(addon=addon, user=author)
        AddonUser.objects.create(addon=addon, user=author2)
        addon2 = addon_factory(slug='another-addon', name=u'Another Addôn',
                               tags=['unique_tag', 'some_tag'],
                               popularity=333)
        AddonUser.objects.create(addon=addon2, user=author2)
        another_addon = addon_factory()
        AddonUser.objects.create(addon=another_addon, user=another_author)
        self.reindex(Addon)

        data = self.perform_search(self.url, {'author': u'foo,bar'})
        assert data['count'] == 2
        assert len(data['results']) == 2

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['slug'] == addon.slug
        result = data['results'][1]
        assert result['id'] == addon2.pk
        assert result['slug'] == addon2.slug

        # repeat with author ids
        data = self.perform_search(
            self.url, {'author': u'%s,%s' % (author.pk, author2.pk)})
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
            self.url, {'author': u'%s,%s' % (author.pk, author2.username)})
        assert data['count'] == 2
        assert len(data['results']) == 2

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['slug'] == addon.slug
        result = data['results'][1]
        assert result['id'] == addon2.pk
        assert result['slug'] == addon2.slug

    def test_filter_by_guid(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              guid='random@guid', popularity=999)
        addon_factory()
        self.reindex(Addon)

        data = self.perform_search(self.url, {'guid': u'random@guid'})
        assert data['count'] == 1
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['slug'] == addon.slug

    def test_filter_by_multiple_guid(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              guid='random@guid', popularity=999)
        addon2 = addon_factory(slug='another-addon', name=u'Another Addôn',
                               guid='random2@guid',
                               popularity=333)
        addon_factory()
        self.reindex(Addon)

        data = self.perform_search(
            self.url, {'guid': u'random@guid,random2@guid'})
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
            self.url, {
                'guid': u'random@guid,invalid@guid,notevenaguid$,random2@guid'}
        )
        assert data['count'] == len(data['results']) == 2
        assert data['results'][0]['id'] == addon.pk
        assert data['results'][1]['id'] == addon2.pk

    def test_filter_by_guid_return_to_amo(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              guid='random@guid', popularity=999)
        DiscoveryItem.objects.create(addon=addon)
        addon_factory()
        self.reindex(Addon)

        # We need to keep force_text because urlsafe_base64_encode only starts
        # returning a string from Django 2.2 onwards, before that a bytestring.
        param = 'rta:%s' % force_text(
            urlsafe_base64_encode(force_bytes(addon.guid)))

        data = self.perform_search(
            self.url, {'guid': param}, expected_queries=1)
        assert data['count'] == 1
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['slug'] == addon.slug

    def test_filter_by_guid_return_to_amo_not_part_of_safe_list(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              guid='random@guid', popularity=999)
        addon_factory()
        self.reindex(Addon)

        # We need to keep force_text because urlsafe_base64_encode only starts
        # returning a string from Django 2.2 onwards, before that a bytestring.
        param = 'rta:%s' % force_text(
            urlsafe_base64_encode(force_bytes(addon.guid)))

        data = self.perform_search(
            self.url, {'guid': param}, expected_status=400, expected_queries=1)
        assert data == [u'Invalid Return To AMO guid (not a curated add-on)']

    def test_filter_by_guid_return_to_amo_wrong_format(self):
        # We need to keep force_text because urlsafe_base64_encode only starts
        # returning a string from Django 2.2 onwards, before that a bytestring.
        param = 'rta:%s' % force_text(urlsafe_base64_encode(b'foo@bar')[:-1])

        data = self.perform_search(
            self.url, {'guid': param}, expected_status=400)
        assert data == [
            u'Invalid Return To AMO guid (not in base64url format?)']

    def test_filter_by_guid_return_to_amo_garbage(self):
        # 'garbage' does decode using base64, but would lead to an
        # UnicodeDecodeError - invalid start byte.
        param = 'rta:garbage'
        data = self.perform_search(
            self.url, {'guid': param}, expected_status=400)
        assert data == [
            u'Invalid Return To AMO guid (not in base64url format?)']

        # Empty param is just as bad.
        param = 'rta:'
        data = self.perform_search(
            self.url, {'guid': param}, expected_status=400)
        assert data == [
            u'Invalid Return To AMO guid (not in base64url format?)']

    def test_filter_by_guid_return_to_amo_feature_disabled(self):
        self.create_switch('return-to-amo', active=False)
        assert not switch_is_active('return-to-amo')
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              guid='random@guid', popularity=999)
        addon_factory()
        self.reindex(Addon)

        # We need to keep force_text because urlsafe_base64_encode only starts
        # returning a string from Django 2.2 onwards, before that a bytestring.
        param = 'rta:%s' % force_text(
            urlsafe_base64_encode(force_bytes(addon.guid)))

        data = self.perform_search(
            self.url, {'guid': param}, expected_status=400)
        assert data == [u'Return To AMO is currently disabled']

    def test_find_addon_default_non_en_us(self):
        with self.activate('en-GB'):
            addon = addon_factory(
                status=amo.STATUS_APPROVED,
                type=amo.ADDON_EXTENSION,
                default_locale='en-GB',
                name='Banana Bonkers',
                description=u'Let your browser eat your bananas',
                summary=u'Banana Summary',
            )

            addon.name = {'es': u'Banana Bonkers espanole'}
            addon.description = {
                'es': u'Deje que su navegador coma sus plátanos'}
            addon.summary = {'es': u'resumen banana'}
            addon.save()

        addon_factory(
            slug='English Addon', name=u'My English Addôn')

        self.reindex(Addon)

        for locale in ('en-US', 'en-GB', 'es'):
            with self.activate(locale):
                url = reverse_ns('addon-search')

                data = self.perform_search(url, {'lang': locale})

                assert data['count'] == 2
                assert len(data['results']) == 2

                data = self.perform_search(
                    url, {'q': 'Banana', 'lang': locale})

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
            self.url, {'exclude_addons': u','.join(
                (addon2.slug, addon3.slug))})

        assert len(data['results']) == 1
        assert data['count'] == 1
        assert data['results'][0]['id'] == addon1.pk

        # Exclude addon1 and addon2 by pk.
        data = self.perform_search(
            self.url, {'exclude_addons': u','.join(
                map(str, (addon2.pk, addon1.pk)))})

        assert len(data['results']) == 1
        assert data['count'] == 1
        assert data['results'][0]['id'] == addon3.pk

        # Exclude addon1 by pk and addon3 by slug.
        data = self.perform_search(
            self.url, {'exclude_addons': u','.join(
                (str(addon1.pk), addon3.slug))})

        assert len(data['results']) == 1
        assert data['count'] == 1
        assert data['results'][0]['id'] == addon2.pk

    def test_filter_fuzziness(self):
        with self.activate('de'):
            addon = addon_factory(slug='my-addon', name={
                'de': 'Mein Taschenmesser'
            }, default_locale='de')

            # Won't get matched, we have a prefix length of 4 so that
            # the first 4 characters are not analyzed for fuzziness
            addon_factory(slug='my-addon2', name={
                'de': u'Mein Hufrinnenmesser'
            }, default_locale='de')

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
        for i in range(0, 10):
            addon_factory()
        self.refresh()
        query = (u'남포역립카페추천 ˇjjtat닷컴ˇ ≡제이제이♠♣ 남포역스파 '
                 u'남포역op남포역유흥≡남포역안마남포역오피 ♠♣')
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
        self.make_addon_recommended(addon2, approve_version=True)
        self.make_addon_recommended(addon4, approve_version=True)
        self.refresh()

        data = self.perform_search(self.url)  # No query.

        ids = [result['id'] for result in data['results']]
        # addon2 and addon4 will be first because they're recommended
        assert ids == [addon2.id, addon4.id, addon1.id, addon3.id, addon5.id]


class TestAddonAutoCompleteSearchView(ESTestCase):
    client_class = APITestClient

    fixtures = ['base/users']

    def setUp(self):
        super(TestAddonAutoCompleteSearchView, self).setUp()
        self.url = reverse_ns('addon-autocomplete', api_version='v5')

    def tearDown(self):
        super(TestAddonAutoCompleteSearchView, self).tearDown()
        self.empty_index('default')
        self.refresh()

    def perform_search(self, url, data=None, expected_status=200,
                       expected_queries=0, **headers):
        with self.assertNumQueries(expected_queries):
            response = self.client.get(url, data, **headers)
        assert response.status_code == expected_status
        data = json.loads(force_text(response.content))
        return data

    def test_basic(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn')
        addon2 = addon_factory(slug='my-second-addon', name=u'My second Addôn')
        addon_factory(slug='nonsense', name=u'Nope Nope Nope')
        self.refresh()

        data = self.perform_search(self.url, {'q': 'my'})  # No db query.
        assert 'count' not in data
        assert 'next' not in data
        assert 'prev' not in data
        assert len(data['results']) == 2

        assert {itm['id'] for itm in data['results']} == {addon.pk, addon2.pk}

    def test_type(self):
        addon = addon_factory(
            slug='my-addon', name=u'My Addôn', type=amo.ADDON_EXTENSION)
        addon2 = addon_factory(
            slug='my-second-addon', name=u'My second Addôn',
            type=amo.ADDON_STATICTHEME)
        addon_factory(slug='nonsense', name=u'Nope Nope Nope')
        addon_factory(
            slug='whocares', name=u'My dict', type=amo.ADDON_DICT)
        self.refresh()

        # No db query.
        data = self.perform_search(
            self.url, {'q': 'my', 'type': 'statictheme,extension'})
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
        assert data['results'][0]['name'] == {'pt-BR': 'foobar'}

        # Same deal in en-US.
        data = self.perform_search(self.url, {'q': 'foobar', 'lang': 'en-US'})
        assert data['results'][0]['name'] == {'pt-BR': 'foobar'}

        # And repeat with v3-style flat output when lang is specified:
        overridden_api_gates = {
            'v5': ('l10n_flat_input_output',)}
        with override_settings(DRF_API_GATES=overridden_api_gates):
            data = self.perform_search(self.url, {'q': 'foobar', 'lang': 'fr'})
            assert data['results'][0]['name'] == 'foobar'

            data = self.perform_search(
                self.url, {'q': 'foobar', 'lang': 'en-US'})
            assert data['results'][0]['name'] == 'foobar'

    def test_empty(self):
        data = self.perform_search(self.url)
        assert 'count' not in data
        assert len(data['results']) == 0

    def test_get_queryset_excludes(self):
        addon_factory(slug='my-addon', name=u'My Addôn',
                      popularity=666)
        addon_factory(slug='my-theme', name=u'My Th€me',
                      type=amo.ADDON_STATICTHEME)
        self.refresh()

        view = AddonAutoCompleteSearchView()
        view.request = APIRequestFactory().get('/')
        qset = view.get_queryset()

        includes = set((
            'default_locale', 'icon_type', 'id', 'is_recommended', 'modified',
            'name_translations', 'promoted', 'slug', 'type'))

        assert set(qset.to_dict()['_source']['includes']) == includes

        response = qset.execute()

        # Sort by type to avoid sorting problems before picking the
        # first result. (We have a theme and an add-on)
        hit = sorted(response.hits.hits, key=lambda x: x['_source']['type'])
        assert set(hit[1]['_source'].keys()) == includes

    def test_no_unlisted(self):
        addon_factory(slug='my-addon', name=u'My Addôn',
                      status=amo.STATUS_NULL,
                      popularity=666,
                      version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED})
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
        addon = addon_factory(
            slug='my-addon', name=u'My Addôn', average_daily_users=100)
        addon2 = addon_factory(
            slug='my-second-addon', name=u'My second Addôn',
            average_daily_users=200)
        addon_factory(slug='nonsense', name=u'Nope Nope Nope')
        self.refresh()

        data = self.perform_search(self.url, {'q': 'my', 'sort': 'users'})
        assert 'count' not in data
        assert 'next' not in data
        assert 'prev' not in data
        assert len(data['results']) == 2

        assert {itm['id'] for itm in data['results']} == {addon2.pk, addon.pk}

        # check the sort isn't ignored when the gate is enabled
        overridden_api_gates = {
            'v5': ('autocomplete-sort-param',)}
        with override_settings(DRF_API_GATES=overridden_api_gates):
            data = self.perform_search(self.url, {'q': 'my', 'sort': 'users'})
            assert {itm['id'] for itm in data['results']} == {
                addon.pk, addon2.pk}


class TestAddonFeaturedView(ESTestCase):
    client_class = APITestClient

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
        addon1 = addon_factory(recommended=True)
        addon2 = addon_factory(recommended=True)
        assert addon1.is_recommended
        assert addon2.is_recommended
        addon_factory()  # not recommended so shouldn't show up
        self.refresh()

        response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(force_text(response.content))
        assert data['results']
        assert len(data['results']) == 2
        # order is random
        ids = {result['id'] for result in data['results']}
        assert ids == {addon1.id, addon2.id}

    def test_page_size(self):
        for _ in range(0, 15):
            addon_factory(recommended=True)

        self.refresh()

        # ask for > 10, to check we're not hitting the default ES page size.
        response = self.client.get(self.url + '?page_size=11')
        assert response.status_code == 200
        data = json.loads(force_text(response.content))
        assert data['results']
        assert len(data['results']) == 11

    def test_invalid_app(self):
        response = self.client.get(
            self.url, {'app': 'foxeh', 'type': 'extension'})
        assert response.status_code == 400
        assert json.loads(force_text(response.content)) == [
            'Invalid "app" parameter.']

    def test_invalid_type(self):
        response = self.client.get(self.url, {'app': 'firefox', 'type': 'lol'})
        assert response.status_code == 400
        assert json.loads(force_text(response.content)) == [
            'Invalid "type" parameter.']

    def test_invalid_category(self):
        response = self.client.get(self.url, {
            'category': 'lol', 'app': 'firefox', 'type': 'extension'
        })
        assert response.status_code == 400
        assert json.loads(force_text(response.content)) == [
            'Invalid "category" parameter.']


class TestStaticCategoryView(TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestStaticCategoryView, self).setUp()
        self.url = reverse_ns('category-list')

    def test_basic(self):
        with self.assertNumQueries(0):
            response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(force_text(response.content))

        assert len(data) == 58

        # some basic checks to verify integrity
        entry = data[0]

        assert entry == {
            u'name': u'Feeds, News & Blogging',
            u'weight': 0,
            u'misc': False,
            u'id': 1,
            u'application': u'firefox',
            u'description': (
                u'Download Firefox extensions that remove clutter so you '
                u'can stay up-to-date on social media, catch up on blogs, '
                u'RSS feeds, reduce eye strain, and more.'
            ),
            u'type': u'extension',
            u'slug': u'feeds-news-blogging'
        }

    def test_with_description(self):
        # StaticCategory is immutable, so avoid calling it's __setattr__
        # directly.
        object.__setattr__(CATEGORIES_BY_ID[1], 'description', u'does stuff')
        with self.assertNumQueries(0):
            response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(force_text(response.content))

        assert len(data) == 58

        # some basic checks to verify integrity
        entry = data[0]

        assert entry == {
            u'name': u'Feeds, News & Blogging',
            u'weight': 0,
            u'misc': False,
            u'id': 1,
            u'application': u'firefox',
            u'description': u'does stuff',
            u'type': u'extension',
            u'slug': u'feeds-news-blogging'
        }

    @pytest.mark.needs_locales_compilation
    def test_name_translated(self):
        with self.assertNumQueries(0):
            response = self.client.get(self.url, HTTP_ACCEPT_LANGUAGE='de')

        assert response.status_code == 200
        data = json.loads(force_text(response.content))

        assert data[0]['name'] == 'RSS-Feeds, Nachrichten & Bloggen'

    def test_cache_control(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response['cache-control'] == 'max-age=21600'


class TestLanguageToolsView(TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestLanguageToolsView, self).setUp()
        self.url = reverse_ns('addon-language-tools')

    def test_wrong_app_or_no_app(self):
        response = self.client.get(self.url)
        assert response.status_code == 400
        assert response.data == {
            'detail': u'Invalid or missing app parameter.'}

        response = self.client.get(self.url, {'app': 'foo'})
        assert response.status_code == 400
        assert response.data == {
            'detail': u'Invalid or missing app parameter.'}

    def test_basic(self):
        dictionary = addon_factory(type=amo.ADDON_DICT, target_locale='fr')
        dictionary_spelling_variant = addon_factory(
            type=amo.ADDON_DICT, target_locale='fr')
        language_pack = addon_factory(
            type=amo.ADDON_LPAPP, target_locale='es',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'})

        # These add-ons below should be ignored: they are either not public or
        # of the wrong type, or their target locale is empty.
        addon_factory(
            type=amo.ADDON_DICT, target_locale='fr',
            version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED})
        addon_factory(
            type=amo.ADDON_LPAPP, target_locale='es',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            status=amo.STATUS_NOMINATED)
        addon_factory(type=amo.ADDON_DICT, target_locale='')
        addon_factory(type=amo.ADDON_LPAPP, target_locale=None)
        addon_factory(target_locale='fr')

        response = self.client.get(self.url, {'app': 'firefox'})
        assert response.status_code == 200
        data = json.loads(force_text(response.content))
        assert len(data['results']) == 3
        expected = [dictionary, dictionary_spelling_variant, language_pack]
        assert len(data['results']) == len(expected)
        assert (
            set(item['id'] for item in data['results']) ==
            set(item.pk for item in expected))

        assert 'locale_disambiguation' not in data['results'][0]
        assert 'target_locale' in data['results'][0]
        # We were not filtering by appversion, so we do not get the
        # current_compatible_version property.
        assert 'current_compatible_version' not in data['results'][0]

    def test_with_appversion_but_no_type(self):
        response = self.client.get(
            self.url, {'app': 'firefox', 'appversion': '57.0'})
        assert response.status_code == 400
        assert response.data == {
            'detail': 'Invalid or missing type parameter while appversion '
                      'parameter is set.'}

    def test_with_invalid_appversion(self):
        response = self.client.get(
            self.url,
            {'app': 'firefox', 'type': 'language', 'appversion': u'foôbar'})
        assert response.status_code == 400
        assert response.data == {'detail': 'Invalid appversion parameter.'}

    def test_with_author_filtering(self):
        user = user_factory(username=u'mozillä')
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
            self.url,
            {'app': 'firefox', 'type': 'language', 'author': u'mozillä'})
        assert response.status_code == 200
        data = json.loads(force_text(response.content))
        expected = [addon1, addon2]

        assert len(data['results']) == len(expected)
        assert (
            set(item['id'] for item in data['results']) ==
            set(item.pk for item in expected))

    def test_with_multiple_authors_filtering(self):
        user1 = user_factory(username=u'mozillä')
        user2 = user_factory(username=u'firefôx')
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
            {'app': 'firefox', 'type': 'language',
             'author': u'mozillä,firefôx'})
        assert response.status_code == 200
        data = json.loads(force_text(response.content))
        expected = [addon1, addon2]
        assert len(data['results']) == len(expected)
        assert (
            set(item['id'] for item in data['results']) ==
            set(item.pk for item in expected))

    def test_with_appversion_filtering(self):
        # Add compatible add-ons. We're going to request language packs
        # compatible with 58.0.
        compatible_pack1 = addon_factory(
            name='Spanish Language Pack',
            type=amo.ADDON_LPAPP, target_locale='es',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'})
        compatible_pack1.current_version.update(created=self.days_ago(2))
        compatible_version1 = version_factory(
            addon=compatible_pack1, file_kw={'strict_compatibility': True},
            min_app_version='58.0', max_app_version='58.*')
        compatible_version1.update(created=self.days_ago(1))
        compatible_pack2 = addon_factory(
            name='French Language Pack',
            type=amo.ADDON_LPAPP, target_locale='fr',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '58.0', 'max_app_version': '58.*'})
        compatible_version2 = compatible_pack2.current_version
        compatible_version2.update(created=self.days_ago(1))
        version_factory(
            addon=compatible_pack2, file_kw={'strict_compatibility': True},
            min_app_version='59.0', max_app_version='59.*')
        # Add a more recent version for both add-ons, that would be compatible
        # with 58.0, but is not public/listed so should not be returned.
        version_factory(
            addon=compatible_pack1, file_kw={'strict_compatibility': True},
            min_app_version='58.0', max_app_version='58.*',
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        version_factory(
            addon=compatible_pack2,
            file_kw={'strict_compatibility': True,
                     'status': amo.STATUS_DISABLED},
            min_app_version='58.0', max_app_version='58.*')
        # And for the first pack, add a couple of versions that are also
        # compatible. We should not use them though, because we only need to
        # return the latest public version that is compatible.
        extra_compatible_version_1 = version_factory(
            addon=compatible_pack1, file_kw={'strict_compatibility': True},
            min_app_version='58.0', max_app_version='58.*')
        extra_compatible_version_1.update(created=self.days_ago(3))
        extra_compatible_version_2 = version_factory(
            addon=compatible_pack1, file_kw={'strict_compatibility': True},
            min_app_version='58.0', max_app_version='58.*')
        extra_compatible_version_2.update(created=self.days_ago(4))

        # Add a few of incompatible add-ons.
        incompatible_pack1 = addon_factory(
            name='German Language Pack (incompatible with 58.0)',
            type=amo.ADDON_LPAPP, target_locale='fr',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '56.0', 'max_app_version': '56.*'})
        version_factory(
            addon=incompatible_pack1, file_kw={'strict_compatibility': True},
            min_app_version='59.0', max_app_version='59.*')
        addon_factory(
            name='Italian Language Pack (incompatible with 58.0)',
            type=amo.ADDON_LPAPP, target_locale='it',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '59.0', 'max_app_version': '59.*'})
        # Even add a pack with a compatible version... not public. And another
        # one with a compatible version... not listed.
        incompatible_pack2 = addon_factory(
            name='Japanese Language Pack (public, but 58.0 version is not)',
            type=amo.ADDON_LPAPP, target_locale='ja',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'})
        version_factory(
            addon=incompatible_pack2,
            min_app_version='58.0', max_app_version='58.*',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW,
                     'strict_compatibility': True})
        incompatible_pack3 = addon_factory(
            name='Nederlands Language Pack (58.0 version is unlisted)',
            type=amo.ADDON_LPAPP, target_locale='ja',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'})
        version_factory(
            addon=incompatible_pack3,
            min_app_version='58.0', max_app_version='58.*',
            channel=amo.RELEASE_CHANNEL_UNLISTED,
            file_kw={'strict_compatibility': True})

        # Test it.
        with self.assertNumQueries(5):
            # 5 queries, regardless of how many add-ons are returned:
            # - 1 for the add-ons
            # - 1 for the add-ons translations (name)
            # - 1 for the compatible versions (through prefetch_related)
            # - 1 for the applications versions for those versions
            #     (we don't need it, but we're using the default Version
            #      transformer to get the files... this could be improved.)
            # - 1 for the files for those versions
            response = self.client.get(
                self.url,
                {'app': 'firefox', 'appversion': '58.0', 'type': 'language',
                 'lang': 'en-US'})
        assert response.status_code == 200, response.content
        results = response.data['results']
        assert len(results) == 2

        # Ordering is not guaranteed by this API, but do check that the
        # current_compatible_version returned makes sense.
        assert results[0]['current_compatible_version']
        assert results[1]['current_compatible_version']

        expected_versions = set((
            (compatible_pack1.pk, compatible_version1.pk),
            (compatible_pack2.pk, compatible_version2.pk),
        ))
        returned_versions = set((
            (results[0]['id'], results[0]['current_compatible_version']['id']),
            (results[1]['id'], results[1]['current_compatible_version']['id']),
        ))
        assert expected_versions == returned_versions

    def test_memoize(self):
        addon_factory(type=amo.ADDON_DICT, target_locale='fr')
        addon_factory(
            type=amo.ADDON_DICT, target_locale='fr')
        addon_factory(type=amo.ADDON_LPAPP, target_locale='es')

        with self.assertNumQueries(2):
            response = self.client.get(
                self.url, {'app': 'firefox', 'lang': 'fr'})
        assert response.status_code == 200
        assert len(json.loads(force_text(response.content))['results']) == 3

        # Same again, should be cached; no queries.
        with self.assertNumQueries(0):
            assert self.client.get(
                self.url, {'app': 'firefox', 'lang': 'fr'}).content == (
                    response.content
            )

        with self.assertNumQueries(2):
            assert (
                self.client.get(
                    self.url, {'app': 'android', 'lang': 'fr'}).content !=
                response.content
            )
        # Same again, should be cached; no queries.
        with self.assertNumQueries(0):
            self.client.get(self.url, {'app': 'android', 'lang': 'fr'})
        # Change the lang, we should get queries again.
        with self.assertNumQueries(2):
            self.client.get(self.url, {'app': 'firefox', 'lang': 'de'})


class TestReplacementAddonView(TestCase):
    client_class = APITestClient

    def test_basic(self):
        # Add a single addon replacement
        rep_addon1 = addon_factory()
        ReplacementAddon.objects.create(
            guid='legacy2addon@moz',
            path=urlunquote(rep_addon1.get_url_path()))
        # Add a collection replacement
        author = user_factory()
        collection = collection_factory(author=author)
        rep_addon2 = addon_factory()
        rep_addon3 = addon_factory()
        CollectionAddon.objects.create(addon=rep_addon2, collection=collection)
        CollectionAddon.objects.create(addon=rep_addon3, collection=collection)
        ReplacementAddon.objects.create(
            guid='legacy2collection@moz',
            path=urlunquote(collection.get_url_path()))
        # Add an invalid path
        ReplacementAddon.objects.create(
            guid='notgonnawork@moz',
            path='/addon/áddonmissing/')

        response = self.client.get(reverse_ns('addon-replacement-addon'))
        assert response.status_code == 200
        data = json.loads(force_text(response.content))
        results = data['results']
        assert len(results) == 3
        assert ({'guid': 'legacy2addon@moz',
                 'replacement': [rep_addon1.guid]} in results)
        assert ({'guid': 'legacy2collection@moz',
                 'replacement': [rep_addon2.guid, rep_addon3.guid]} in results)
        assert ({'guid': 'notgonnawork@moz',
                 'replacement': []} in results)


class TestCompatOverrideView(TestCase):
    """This view is used by Firefox directly and queried a lot.

    But now we don't have any CompatOverrides we just return an empty response.
    """

    client_class = APITestClient

    def test_response(self):
        response = self.client.get(
            reverse_ns('addon-compat-override', api_version='v3'),
            data={'guid': u'extrabad@thing,bad@thing'})
        assert response.status_code == 200
        data = json.loads(force_text(response.content))
        results = data['results']
        assert len(results) == 0


class TestAddonRecommendationView(ESTestCase):
    client_class = APITestClient

    fixtures = ['base/users']

    def setUp(self):
        super(TestAddonRecommendationView, self).setUp()
        self.url = reverse_ns('addon-recommendations')
        patcher = mock.patch(
            'olympia.addons.views.get_addon_recommendations')
        self.get_addon_recommendations_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        super(TestAddonRecommendationView, self).tearDown()
        self.empty_index('default')
        self.refresh()

    def perform_search(self, url, data=None, expected_status=200,
                       expected_queries=0, **headers):
        with self.assertNumQueries(expected_queries):
            response = self.client.get(url, data, **headers)
        assert response.status_code == expected_status, response.content
        data = json.loads(force_text(response.content))
        return data

    def test_basic(self):
        addon1 = addon_factory(id=101, guid='101@mozilla')
        addon2 = addon_factory(id=102, guid='102@mozilla')
        addon3 = addon_factory(id=103, guid='103@mozilla')
        addon4 = addon_factory(id=104, guid='104@mozilla')
        self.get_addon_recommendations_mock.return_value = (
            ['101@mozilla', '102@mozilla', '103@mozilla', '104@mozilla'],
            'recommended', 'no_reason')
        self.refresh()

        data = self.perform_search(
            self.url, {'guid': 'foo@baa', 'recommended': 'False'})
        self.get_addon_recommendations_mock.assert_called_with(
            'foo@baa', False)
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
            'recommended', None)
        get_addon_recommendations_invalid.return_value = (
            ['105@mozilla', '106@mozilla', '107@mozilla', '108@mozilla'],
            'failed', 'invalid')
        self.refresh()

        data = self.perform_search(
            self.url, {'guid': 'foo@baa', 'recommended': 'True'})
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
        data = self.perform_search(
            self.url, {'guid': 'foo@baa', 'recommended': 'True'})
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
        self.get_addon_recommendations_mock.return_value = (
            ['@a', '@b'], 'foo', 'baa')
        with patch.object(
                Elasticsearch, 'search',
                wraps=amo.search.get_es().search) as search_mock:
            with patch.object(
                    Elasticsearch, 'count',
                    wraps=amo.search.get_es().count) as count_mock:
                data = self.perform_search(self.url, data={'guid': '@foo'})
                assert data['count'] == 0
                assert len(data['results']) == 0
                assert search_mock.call_count == 1
                assert count_mock.call_count == 0

    def test_es_queries_made_results(self):
        addon_factory(slug='foormidable', name=u'foo', guid='@a')
        addon_factory(slug='foobar', name=u'foo', guid='@b')
        addon_factory(slug='fbar', name=u'foo', guid='@c')
        addon_factory(slug='fb', name=u'foo', guid='@d')
        self.refresh()

        self.get_addon_recommendations_mock.return_value = (
            ['@a', '@b', '@c', '@d'], 'recommended', None)
        with patch.object(
                Elasticsearch, 'search',
                wraps=amo.search.get_es().search) as search_mock:
            with patch.object(
                    Elasticsearch, 'count',
                    wraps=amo.search.get_es().count) as count_mock:
                data = self.perform_search(
                    self.url, data={'guid': '@foo', 'recommended': 'true'})
                assert data['count'] == 4
                assert len(data['results']) == 4
                assert search_mock.call_count == 1
                assert count_mock.call_count == 0
