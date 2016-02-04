"""Testing the pytest fixtures themselves which are declared in conftest.py."""

from olympia.access.models import Group


def test_admin_group(admin_group):
    assert Group.objects.count() == 1
    admin_group = Group.objects.get()
    assert admin_group.name == 'Admins'
    assert admin_group.rules == '*:*'


def test_mozilla_user(mozilla_user):
    assert mozilla_user.check_password('password')
    admin_group = mozilla_user.groups.get()
    assert admin_group.name == 'Admins'
    assert admin_group.rules == '*:*'
