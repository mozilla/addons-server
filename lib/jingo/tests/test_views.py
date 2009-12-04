from mock import patch, sentinel

import jingo.views


@patch('jingo.render')
def test_direct_to_template(mock_render):
    request = sentinel.request
    jingo.views.direct_to_template(request, 'base.html', x=1)
    mock_render.assert_called_with(request, 'base.html', {'x': 1})
