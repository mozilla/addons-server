from django import http

import mock
from nose.tools import eq_

from amo import decorators


def test_post_required():
    f = lambda r: mock.sentinel.response
    g = decorators.post_required(f)

    request = mock.Mock()
    request.method = 'GET'
    assert isinstance(g(request), http.HttpResponseNotAllowed)

    request.method = 'POST'
    eq_(g(request), mock.sentinel.response)


def test_json_view():
    """Turns a Python object into a response."""
    f = lambda r: {'x': 1}
    response = decorators.json_view(f)(mock.Mock())
    assert isinstance(response, http.HttpResponse)
    eq_(response.content, '{"x": 1}')
    eq_(response['Content-Type'], 'application/json')


def test_json_view_normal_response():
    """Normal responses get passed through."""
    expected = http.HttpResponseForbidden()
    f = lambda r: expected
    response = decorators.json_view(f)(mock.Mock())
    assert expected is response
    eq_(response['Content-Type'], 'text/html; charset=utf-8')


def test_json_view_error():
    """json_view.error returns 400 responses."""
    response = decorators.json_view.error({'msg': 'error'})
    assert isinstance(response, http.HttpResponseBadRequest)
    eq_(response.content, '{"msg": "error"}')
    eq_(response['Content-Type'], 'application/json')
