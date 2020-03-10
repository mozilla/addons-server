from unittest import mock

import pytest
from waffle.testutils import override_switch

from olympia.amo.tests import addon_factory, user_factory
from olympia.blocklist.cron import upload_mlbf_to_kinto
from olympia.blocklist.mlbf import get_mlbf_key_format
from olympia.blocklist.models import Block
from olympia.lib.kinto import KintoServer


@pytest.mark.django_db
@override_switch('blocklist_mlbf_submit', active=True)
@mock.patch('olympia.blocklist.cron.get_mlbf_key_format')
@mock.patch.object(KintoServer, 'publish_attachment')
def test_upload_mlbf_to_kinto(publish_mock, get_mlbf_key_format_mock):
    key_format = get_mlbf_key_format()
    get_mlbf_key_format_mock.return_value = key_format
    addon_factory()
    Block.objects.create(
        addon=addon_factory(),
        updated_by=user_factory())
    upload_mlbf_to_kinto()

    publish_mock.assert_called_with(
        {'key_format': key_format},
        ('filter.bin', mock.ANY, 'application/octet-stream'))


@pytest.mark.django_db
@override_switch('blocklist_mlbf_submit', active=False)
@mock.patch.object(KintoServer, 'publish_attachment')
def test_waffle_off_disables_publishing(publish_mock):
    addon_factory()
    Block.objects.create(
        addon=addon_factory(),
        updated_by=user_factory())
    upload_mlbf_to_kinto()

    publish_mock.assert_not_called()
