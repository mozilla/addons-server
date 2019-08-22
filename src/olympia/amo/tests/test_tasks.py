import json

from django.core.exceptions import ImproperlyConfigured

import responses

from waffle.testutils import override_switch


from olympia.accounts.serializers import UserProfileBasketSyncSerializer
from olympia.addons.serializers import AddonBasketSyncSerializer
from olympia.amo.tasks import sync_object_to_basket
from olympia.amo.tests import addon_factory, TestCase, user_factory


@override_switch('basket-amo-sync', active=True)
class TestSyncObjectToBasket(TestCase):
    def test_unsupported(self):
        with self.assertRaises(ImproperlyConfigured):
            sync_object_to_basket('version', 42)

    @override_switch('basket-amo-sync', active=False)
    def test_switch_is_not_active(self):
        addon = addon_factory()
        sync_object_to_basket('addon', addon.pk)
        assert len(responses.calls) == 0

    def test_addon(self):
        responses.add(
            responses.POST,
            'https://basket.allizom.org/amo-sync/addon/',
            json=True)
        with override_switch('basket-amo-sync', active=False):
            # Gotta deactivate the sync when calling addon_factory() because
            # the change to _current_version inside will trigger a sync.
            addon = addon_factory()
        sync_object_to_basket('addon', addon.pk)
        assert len(responses.calls) == 1
        body = responses.calls[0].request.body
        data = json.loads(body)
        expected_data = AddonBasketSyncSerializer(addon).data
        assert expected_data
        assert data == expected_data

    def test_userprofile(self):
        responses.add(
            responses.POST,
            'https://basket.allizom.org/amo-sync/userprofile/',
            json=True)
        user = user_factory()
        sync_object_to_basket('userprofile', user.pk)
        assert len(responses.calls) == 1
        body = responses.calls[0].request.body
        data = json.loads(body)
        expected_data = UserProfileBasketSyncSerializer(user).data
        assert expected_data
        assert data == expected_data
