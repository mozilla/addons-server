from django.test.utils import override_settings

from apps.accounts import helpers


@override_settings(FXA_CONFIG={
    'client_id': 'foo',
    'client_secret': 'bar',
    'something': 'hello, world!',
    'a_different_thing': 'howdy, world!',
})
def test_fxa_config():
    assert helpers.fxa_config() == {
        'clientId': 'foo',
        'something': 'hello, world!',
        'aDifferentThing': 'howdy, world!',
    }
