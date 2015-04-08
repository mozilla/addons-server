import mock

from django.conf import settings
from django.core.management import call_command


@mock.patch('lib.crypto.tasks.sign_addons')
def test_override_settings(mock_sign_addons):
    """You can override the (PRELIMINARY_)SIGNING_SERVER settings."""
    assert not settings.SIGNING_SERVER
    assert not settings.PRELIMINARY_SIGNING_SERVER

    # No endpoint defined in the test settings.
    def no_endpoint(ids):
        assert not settings.SIGNING_SERVER
    mock_sign_addons.side_effect = no_endpoint
    call_command('sign_addons', 123)
    assert mock_sign_addons.called

    mock_sign_addons.reset_mock()

    # Override the SIGNING_SERVER setting.
    def signing_server(ids):
        assert settings.SIGNING_SERVER == 'http://example.com'
    mock_sign_addons.side_effect = signing_server
    call_command('sign_addons', 123, signing_server='http://example.com')
    assert mock_sign_addons.called

    mock_sign_addons.reset_mock()

    # Override the PRELIMINARY_SIGNING_SERVER setting.
    def preliminary_signing_server(ids):
        assert settings.PRELIMINARY_SIGNING_SERVER == 'http://example.com'
    mock_sign_addons.side_effect = preliminary_signing_server
    call_command('sign_addons', 123,
                 preliminary_signing_server='http://example.com')
    assert mock_sign_addons.called
