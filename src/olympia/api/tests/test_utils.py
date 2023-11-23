from django.test import override_settings

from rest_framework.test import APIRequestFactory

from ..utils import APIChoices, APIChoicesWithDash, APIChoicesWithNone, is_gate_active


factory = APIRequestFactory()


@override_settings(DRF_API_GATES={'v1': None, 'v2': {'foo'}})
def test_is_gate_active():
    request = factory.get('/')

    assert not is_gate_active(request, 'foo')

    request.version = 'v2'

    assert is_gate_active(request, 'foo')


@override_settings(DRF_API_GATES={'v1': None, 'v2': {'foo'}, 'v3': {'baa'}})
def test_is_gate_active_explicit_upgrades():
    # Test that we're not implicitly upgrading feature gates
    request = factory.get('/')

    assert not is_gate_active(request, 'baa')

    request.version = 'v2'

    assert not is_gate_active(request, 'baa')

    request.version = 'v3'

    assert is_gate_active(request, 'baa')


def test_api_choices():
    choices = APIChoices(
        ('NO_DECISION', 0, 'No decision'),
        ('AMO_BAN_USER', 1, 'User ban'),
    )
    assert choices.api_choices == ((0, 'no_decision'), (1, 'amo_ban_user'))
    assert choices.has_api_value('no_decision') is True
    assert choices.for_api_value('no_decision') == ('NO_DECISION', 0, 'No decision')
    assert choices.for_value(choices.NO_DECISION).api_value == 'no_decision'


def test_api_choices_with_none():
    choices = APIChoicesWithNone(
        ('NO_DECISION', 0, 'No decision'),
        ('AMO_BAN_USER', 1, 'User ban'),
    )
    assert choices.api_choices == (
        (None, None),
        (0, 'no_decision'),
        (1, 'amo_ban_user'),
    )
    assert choices.has_api_value('no_decision') is True
    assert choices.for_api_value('no_decision') == ('NO_DECISION', 0, 'No decision')
    assert choices.for_value(choices.NO_DECISION).api_value == 'no_decision'


def test_api_choices_with_dash():
    choices = APIChoicesWithDash(
        ('NO_DECISION', 0, 'No decision'),
        ('AMO_BAN_USER', 1, 'User ban'),
    )
    assert choices.api_choices == ((0, 'no-decision'), (1, 'amo-ban-user'))
    assert choices.has_api_value('no-decision') is True
    assert choices.for_api_value('no-decision') == ('NO_DECISION', 0, 'No decision')
    assert choices.for_value(choices.NO_DECISION).api_value == 'no-decision'
