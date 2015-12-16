from django.test.utils import override_settings

import mock

from olympia.apps.accounts import helpers


@override_settings(FXA_CONFIG={
    'client_id': 'foo',
    'client_secret': 'bar',
    'something': 'hello, world!',
    'a_different_thing': 'howdy, world!',
})
def test_fxa_config():
    context = mock.MagicMock()
    context['request'].session = {'fxa_state': 'thestate!'}
    assert helpers.fxa_config(context) == {
        'clientId': 'foo',
        'something': 'hello, world!',
        'state': 'thestate!',
        'aDifferentThing': 'howdy, world!',
    }
