from django.contrib.auth.models import AnonymousUser
from django.http.request import HttpHeaders

from olympia import core
from olympia.users.models import UserProfile


def test_override_remote_addr_or_metadata():
    original = core.get_remote_addr()

    with core.override_remote_addr_or_metadata(ip_address='some other value'):
        assert core.get_remote_addr() == 'some other value'

    assert core.get_remote_addr() == original


def test_set_get_user_anonymous():
    core.set_user(AnonymousUser())
    assert core.get_user() is None

    user = UserProfile()
    core.set_user(user)
    assert core.get_user() == user

    core.set_user(None)
    assert core.get_user() is None


def test_get_request_metadata_and_set_request_metadata():
    assert core.get_request_metadata() == {}

    core.set_request_metadata(data=None)
    assert core.get_request_metadata() == {}

    core.set_request_metadata({'a': 'b', 'c': None})
    assert core.get_request_metadata() == {'a': 'b'}


def test_select_request_fingerprint_headers():
    assert core.select_request_fingerprint_headers(HttpHeaders({})) == {}

    assert core.select_request_fingerprint_headers(
        HttpHeaders({'HTTP_Client-JA4': None, 'HTTP_X_SigSci-TAGS': 'SOME,tags'})
    ) == {'X-SigSci-Tags': 'SOME,tags'}
