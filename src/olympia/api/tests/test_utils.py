from django.test import override_settings

from rest_framework.test import APIRequestFactory

from olympia.api.utils import is_gate_active

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
