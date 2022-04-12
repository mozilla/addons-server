from unittest import mock

import pytest

from waffle.models import Switch

# Note: unit testing custom migration operations is a pain, so we cheat and
# test with mocks for the state and schema editor, passing current app state.
from django.apps.registry import apps

from olympia.core.db.migrations import CreateWaffleSwitch, DeleteWaffleSwitch


@pytest.mark.django_db
def test_delete_waffle_switch_forward():
    Switch.objects.create(name='foo')
    schema_editor = mock.Mock(connection=mock.Mock(alias='default'))
    from_state = mock.Mock(apps=apps)
    to_state = mock.Mock()
    DeleteWaffleSwitch('foo').database_forwards(
        'fake_app', schema_editor, from_state, to_state
    )
    assert not Switch.objects.filter(name='foo').exists()


@pytest.mark.django_db
def test_delete_waffle_switch_reverse():
    schema_editor = mock.Mock(connection=mock.Mock(alias='default'))
    from_state = mock.Mock(apps=apps)
    to_state = mock.Mock()
    DeleteWaffleSwitch('foo').database_backwards(
        'fake_app', schema_editor, from_state, to_state
    )
    assert Switch.objects.filter(name='foo').exists()


@pytest.mark.django_db
def test_delete_waffle_switch_reverse_already_exists():
    Switch.objects.create(name='foo')
    schema_editor = mock.Mock(connection=mock.Mock(alias='default'))
    from_state = mock.Mock(apps=apps)
    to_state = mock.Mock()
    DeleteWaffleSwitch('foo').database_backwards(
        'fake_app', schema_editor, from_state, to_state
    )
    assert Switch.objects.filter(name='foo').exists()


@pytest.mark.django_db
def test_create_waffle_switch_forward():
    schema_editor = mock.Mock(connection=mock.Mock(alias='default'))
    from_state = mock.Mock(apps=apps)
    to_state = mock.Mock()
    CreateWaffleSwitch('foo').database_forwards(
        'fake_app', schema_editor, from_state, to_state
    )
    assert Switch.objects.filter(name='foo').exists()


@pytest.mark.django_db
def test_create_waffle_switch_forward_already_exists():
    Switch.objects.create(name='foo')
    schema_editor = mock.Mock(connection=mock.Mock(alias='default'))
    from_state = mock.Mock(apps=apps)
    to_state = mock.Mock()
    CreateWaffleSwitch('foo').database_forwards(
        'fake_app', schema_editor, from_state, to_state
    )
    assert Switch.objects.filter(name='foo').exists()


@pytest.mark.django_db
def test_create_waffle_switch_reverse():
    Switch.objects.create(name='foo')
    schema_editor = mock.Mock(connection=mock.Mock(alias='default'))
    from_state = mock.Mock(apps=apps)
    to_state = mock.Mock()
    CreateWaffleSwitch('foo').database_backwards(
        'fake_app', schema_editor, from_state, to_state
    )
    assert not Switch.objects.filter(name='foo').exists()
