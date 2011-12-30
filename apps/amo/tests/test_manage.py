import sys

from mock import patch
from nose.tools import eq_


@patch.object(sys, 'argv', ['manage.py'])
def test_manage():
    import manage
    reload(manage)
    assert manage.settings, '"settings_local" was not imported'
    # We're not running tests, so import settings_local.
    eq_(manage.has_settings_local, True)


@patch.object(sys, 'argv', ['manage.py', 'syncdb'])
def test_manage_syncdb():
    import manage
    reload(manage)
    assert manage.settings, '"settings_local" was not imported'
    eq_(manage.has_settings_local, True)


@patch.object(sys, 'argv', ['manage.py', 'test'])
def test_manage_test():
    import manage
    reload(manage)
    assert manage.settings, '"settings" was not imported'
    # We're running tests, so settings_local should not be imported.
    eq_(manage.has_settings_local, False)
