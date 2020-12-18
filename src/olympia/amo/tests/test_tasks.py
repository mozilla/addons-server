import json
from unittest import mock

import responses
from requests.exceptions import HTTPError
from waffle.testutils import override_switch

from django.core.exceptions import ImproperlyConfigured
from django.conf import settings
from django.test.utils import override_settings

from olympia.accounts.serializers import UserProfileBasketSyncSerializer
from olympia.addons.serializers import AddonBasketSyncSerializer
from olympia.amo.tasks import sync_objects_to_basket, trigger_sync_objects_to_basket
from olympia.amo.tests import addon_factory, TestCase, user_factory


@override_switch('basket-amo-sync', active=True)
class TestSyncObjectToBasket(TestCase):
    def test_unsupported(self):
        with self.assertRaises(ImproperlyConfigured):
            sync_objects_to_basket('version', [42])

    @override_switch('basket-amo-sync', active=False)
    def test_switch_is_not_active(self):
        addon = addon_factory()
        sync_objects_to_basket('addon', [addon.pk])
        assert len(responses.calls) == 0

    @mock.patch('olympia.amo.tasks.sync_objects_to_basket')
    def test_trigger_sync_to_basket_wrapper(self, sync_objects_to_basket_mock):
        trigger_sync_objects_to_basket('blah', [4815162342], 'reason')

        assert sync_objects_to_basket_mock.delay.call_count == 1
        sync_objects_to_basket_mock.delay.assert_called_with('blah', [4815162342])

    @override_switch('basket-amo-sync', active=False)
    @mock.patch('olympia.amo.tasks.sync_objects_to_basket')
    def test_trigger_sync_to_basket_wrapper_switch_is_not_active(
        self, sync_objects_to_basket_mock
    ):
        trigger_sync_objects_to_basket('blah', [4815162342], 'reason')

        assert sync_objects_to_basket_mock.delay.call_count == 0

    @override_settings(BASKET_API_KEY='a-basket-key')
    def test_addon(self):
        responses.add(
            responses.POST, 'https://basket.allizom.org/amo-sync/addon/', json=True
        )
        with override_switch('basket-amo-sync', active=False):
            # Gotta deactivate the sync when calling addon_factory() because
            # the change to _current_version inside will trigger a sync.
            addon = addon_factory()
        sync_objects_to_basket('addon', [addon.pk])
        assert len(responses.calls) == 1
        request = responses.calls[0].request
        assert request.headers['x-api-key'] == settings.BASKET_API_KEY
        body = request.body
        data = json.loads(body)
        expected_data = AddonBasketSyncSerializer(addon).data
        assert expected_data
        assert data == expected_data

    @override_settings(BASKET_API_KEY=None)
    def test_addon_error_raises(self):
        responses.add(
            responses.POST,
            'https://basket.allizom.org/amo-sync/addon/',
            json=True,
            status=403,
        )
        with override_switch('basket-amo-sync', active=False):
            # Gotta deactivate the sync when calling addon_factory() because
            # the change to _current_version inside will trigger a sync.
            addon = addon_factory()
        with self.assertRaises(HTTPError):
            sync_objects_to_basket('addon', [addon.pk])

        assert len(responses.calls) == 1
        request = responses.calls[0].request
        assert request.headers['x-api-key'] == ''
        body = request.body
        data = json.loads(body)
        expected_data = AddonBasketSyncSerializer(addon).data
        assert expected_data
        assert data == expected_data

    @override_settings(BASKET_API_KEY='a-basket-key')
    def test_userprofile(self):
        responses.add(
            responses.POST,
            'https://basket.allizom.org/amo-sync/userprofile/',
            json=True,
        )
        user = user_factory()
        sync_objects_to_basket('userprofile', [user.pk])
        assert len(responses.calls) == 1
        request = responses.calls[0].request
        assert request.headers['x-api-key'] == settings.BASKET_API_KEY
        body = request.body
        data = json.loads(body)
        expected_data = UserProfileBasketSyncSerializer(user).data
        assert expected_data
        assert data == expected_data
