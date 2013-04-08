import json
import urllib

from django.test import TestCase

from nose.tools import eq_
from tastypie.exceptions import UnsupportedFormat

from mkt.api.serializers import Serializer


class TestSerializer(TestCase):

    def setUp(self):
        self.s = Serializer()

    def test_json(self):
        eq_(self.s.deserialize(json.dumps({'foo': 'bar'}),
                               'application/json'),
            {'foo': 'bar'})

    def test_url(self):
        eq_(self.s.deserialize(urllib.urlencode({'foo': 'bar'}),
                               'application/x-www-form-urlencoded'),
            {'foo': 'bar'})

    def test_from_url(self):
        with self.assertRaises(UnsupportedFormat):
            self.s.to_urlencode({})
