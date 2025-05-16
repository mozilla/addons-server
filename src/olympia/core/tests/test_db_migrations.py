# Note: unit testing custom migration operations is a pain, so we cheat and
# test with mocks for the state and schema editor, passing current app state.
from unittest import mock

from django.apps import apps

import pytest
from waffle.models import Switch

from olympia.core.db.migrations import (
    CreateWaffleSwitch,
    DeleteWaffleSwitch,
    RenameWaffleSwitch,
)


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


@pytest.mark.django_db
def test_rename_waffle_switch_forward():
    schema_editor = mock.Mock(connection=mock.Mock(alias='default'))
    from_state = mock.Mock(apps=apps)
    to_state = mock.Mock()
    RenameWaffleSwitch('foo', 'baa').database_forwards(
        'fake_app', schema_editor, from_state, to_state
    )
    assert not Switch.objects.filter(name='foo').exists()
    assert Switch.objects.filter(name='baa').exists()


@pytest.mark.django_db
def test_rename_waffle_switch_forward_already_exists():
    Switch.objects.create(name='foo')
    schema_editor = mock.Mock(connection=mock.Mock(alias='default'))
    from_state = mock.Mock(apps=apps)
    to_state = mock.Mock()
    RenameWaffleSwitch('foo', 'baa').database_forwards(
        'fake_app', schema_editor, from_state, to_state
    )
    assert not Switch.objects.filter(name='foo').exists()
    assert Switch.objects.filter(name='baa').exists()


@pytest.mark.django_db
def test_rename_waffle_switch_reverse():
    Switch.objects.create(name='baa')
    schema_editor = mock.Mock(connection=mock.Mock(alias='default'))
    from_state = mock.Mock(apps=apps)
    to_state = mock.Mock()
    RenameWaffleSwitch('foo', 'baa').database_backwards(
        'fake_app', schema_editor, from_state, to_state
    )
    assert Switch.objects.filter(name='foo').exists()
    assert not Switch.objects.filter(name='baa').exists()
