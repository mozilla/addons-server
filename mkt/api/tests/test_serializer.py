# -*- coding: utf-8 -*-
from decimal import Decimal
import json

from django.contrib.auth.models import User
from django.core.handlers.wsgi import WSGIRequest
from django.test import TestCase
from django.utils.http import urlencode

import mock
from nose.tools import eq_, ok_
from rest_framework.serializers import ValidationError
from simplejson import JSONDecodeError
from tastypie.exceptions import UnsupportedFormat
from test_utils import RequestFactory

from mkt.api.exceptions import DeserializationError
from mkt.api.serializers import (PotatoCaptchaSerializer, Serializer,
                                 URLSerializerMixin)
from mkt.site.fixtures import fixture
from mkt.site.tests.test_forms import PotatoCaptchaTestCase


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
        eq_(self.s.deserialize(urlencode({'foo': 'bar'}),
                               'application/x-www-form-urlencoded'),
            {'foo': 'bar'})

        eq_(self.s.deserialize(urlencode({'foo': u'baré'}),
                               'application/x-www-form-urlencoded'),
            {'foo': u'baré'})

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


class TestPotatoCaptchaSerializer(PotatoCaptchaTestCase):
    fixtures = fixture('user_999')

    def test_success_authenticated(self):
        self.request.user = User.objects.get(id=999)
        self.request.user.is_authenticated = lambda: True
        serializer = PotatoCaptchaSerializer(data={}, context=self.context)
        eq_(serializer.is_valid(), True)

    def test_success_anonymous(self):
        data = {'tuber': '', 'sprout': 'potato'}
        serializer = PotatoCaptchaSerializer(data=data, context=self.context)
        eq_(serializer.is_valid(), True)

    def test_no_context(self):
        data = {'tuber': '', 'sprout': 'potato'}
        with self.assertRaises(ValidationError):
            PotatoCaptchaSerializer(data=data)

    def test_error_anonymous_bad_tuber(self):
        data = {'tuber': 'HAMMMMMMMMMMMMM', 'sprout': 'potato'}
        serializer = PotatoCaptchaSerializer(data=data, context=self.context)
        eq_(serializer.is_valid(), False)

    def test_error_anonymous_bad_sprout(self):
        data = {'tuber': 'HAMMMMMMMMMMMMM', 'sprout': ''}
        serializer = PotatoCaptchaSerializer(data=data, context=self.context)
        eq_(serializer.is_valid(), False)

    def test_error_anonymous_bad_tuber_and_sprout(self):
        serializer = PotatoCaptchaSerializer(data={}, context=self.context)
        eq_(serializer.is_valid(), False)


class TestURLSerializerMixin(TestCase):
    SerializerClass = type('Potato', (URLSerializerMixin, Serializer),
                          {'Meta': None})
    Struct = type('Struct', (object,), {})
    url_basename = 'potato'

    def setUp(self):
        self.SerializerClass.Meta = type('Meta', (self.Struct,),
                                        {'model': User,
                                         'url_basename': self.url_basename})
        self.serializer = self.SerializerClass(context=
            {'request': RequestFactory().get('/')})
        self.obj = self.Struct()
        self.obj.pk = 42

    @mock.patch('mkt.api.serializers.reverse')
    def test_get_url(self, mock_reverse):
        self.serializer.get_url(self.obj)
        reverse_args, reverse_kwargs = mock_reverse.call_args
        ok_(mock_reverse.called)
        eq_(reverse_args[0], '%s-detail' % self.url_basename)
        eq_(type(reverse_kwargs['request']), WSGIRequest)
        eq_(reverse_kwargs['kwargs']['pk'], self.obj.pk)
