from django.test.utils import override_settings

import mock

from olympia.accounts import helpers


@override_settings(FXA_CONFIG={
    'client_id': 'foo',
    'client_secret': 'bar',
    'something': 'hello, world!',
    'a_different_thing': 'howdy, world!',
})
def test_fxa_config_anonymous():
    context = mock.MagicMock()
    context['request'].session = {'fxa_state': 'thestate!'}
    context['request'].user.is_authenticated.return_value = False
    assert helpers.fxa_config(context) == {
        'clientId': 'foo',
        'something': 'hello, world!',
        'state': 'thestate!',
        'aDifferentThing': 'howdy, world!',
    }


@override_settings(FXA_CONFIG={
    'client_id': 'foo',
    'client_secret': 'bar',
    'something': 'hello, world!',
    'a_different_thing': 'howdy, world!',
})
def test_fxa_config_logged_in():
    context = mock.MagicMock()
    context['request'].session = {'fxa_state': 'thestate!'}
    context['request'].user.is_authenticated.return_value = True
    context['request'].user.email = 'me@mozilla.org'
    assert helpers.fxa_config(context) == {
        'clientId': 'foo',
        'something': 'hello, world!',
        'state': 'thestate!',
        'aDifferentThing': 'howdy, world!',
        'email': 'me@mozilla.org',
    }
