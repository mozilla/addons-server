import mock
import pytest

from olympia.amo.utils import from_string


pytestmark = pytest.mark.django_db


@mock.patch('olympia.amo.ext.cache._cache_support')
def test_app_in_fragment_cache_key(cache_mock):
    cache_mock.return_value = ''
    request = mock.Mock()
    request.APP.id = '<app>'
    request.user.is_authenticated.return_value = False
    template = from_string('{% cache 1 %}{% endcache %}')
    template.render(request=request)
    assert cache_mock.call_args[0][0].endswith('<app>')


@mock.patch('olympia.amo.ext.cache._cache_support')
def test_fragment_cache_key_no_app(cache_mock):
    cache_mock.return_value = 'xx'
    template = from_string('{% cache 1 %}{% endcache %}')
    assert template.render() == 'xx'
    assert cache_mock.called
