"""Testing the pytest fixtures themselves which are declared in conftest.py."""
import pytest
import responses
import requests

from requests.exceptions import ConnectionError

from olympia.access.models import Group


def test_admin_group(admin_group):
    assert Group.objects.count() == 1
    admin_group = Group.objects.get()
    assert admin_group.name == 'Admins'
    assert admin_group.rules == '*:*'


def test_mozilla_user(mozilla_user):
    admin_group = mozilla_user.groups.get()
    assert admin_group.name == 'Admins'
    assert admin_group.rules == '*:*'


@pytest.mark.allow_external_http_requests
def test_external_requests_enabled():
    with pytest.raises(ConnectionError):
        requests.get('http://example.invalid')

    assert len(responses.calls) == 0


def test_external_requests_disabled_by_default():
    with pytest.raises(ConnectionError):
        requests.get('http://example.invalid')

    assert len(responses.calls) == 1
