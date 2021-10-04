from django.contrib.auth.models import AnonymousUser

from olympia import core
from olympia.users.models import UserProfile


def test_override_remote_addr():
    original = core.get_remote_addr()

    with core.override_remote_addr('some other value'):
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
