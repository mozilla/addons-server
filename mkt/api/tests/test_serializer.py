from decimal import Decimal
import json
import urllib

from django.test import TestCase

from nose.tools import eq_
from simplejson import JSONDecodeError
from tastypie.exceptions import UnsupportedFormat

from mkt.api.exceptions import DeserializationError
from mkt.api.serializers import Serializer


class TestSerializer(TestCase):

    def setUp(self):
        self.s = Serializer()

    def test_json(self):
        eq_(self.s.deserialize(json.dumps({'foo': 'bar'}),
                               'application/json'),
            {'foo': 'bar'})

    def test_decimal(self):
        eq_(self.s.serialize({'foo': Decimal('5.00')}),
            json.dumps({'foo': '5.00'}))

    def test_url(self):
        eq_(self.s.deserialize(urllib.urlencode({'foo': 'bar'}),
                               'application/x-www-form-urlencoded'),
            {'foo': 'bar'})

    def test_from_url(self):
        with self.assertRaises(UnsupportedFormat):
            self.s.to_urlencode({})

    def test_deserialization_error(self):
        try:
            self.s.deserialize('')
        except DeserializationError, e:
            self.assertIsInstance(e.original, JSONDecodeError)
        else:
            self.fail('DeserializationError not raised')
