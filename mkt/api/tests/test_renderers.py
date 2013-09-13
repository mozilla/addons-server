from nose.tools import eq_

from amo.tests import TestCase
from mkt.api.renderers import SuccinctJSONRenderer


class TestSuccinctJSONRenderer(TestCase):
    def setUp(self):
        self.renderer = SuccinctJSONRenderer()
        self.input = {'foo': 'bar'}

    def test_no_spaces(self):
        output = self.renderer.render(self.input)
        eq_(output, '{"foo":"bar"}')

    def test_indent_context(self):
        output = self.renderer.render(self.input,
                                      renderer_context={'indent': 4})
        eq_(output, '{\n    "foo": "bar"\n}')

    def test_accepted_header(self):
        header = 'application/json; indent=4'
        output = self.renderer.render(self.input, accepted_media_type=header)
        eq_(output, '{\n    "foo": "bar"\n}')
