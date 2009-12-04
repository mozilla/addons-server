from nose.tools import eq_
from mock import Mock, patch, sentinel

import jingo


@patch('jingo.env')
def test_render(mock_env):
    mock_template = Mock()
    mock_env.get_template.return_value = mock_template

    response = jingo.render(sentinel.request, sentinel.template, status=32)
    mock_env.get_template.assert_called_with(sentinel.template)
    assert mock_template.render.called

    eq_(response.status_code, 32)
