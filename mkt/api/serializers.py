from urlparse import parse_qsl

from django.utils.simplejson import JSONDecodeError

from tastypie.serializers import Serializer
from tastypie.exceptions import UnsupportedFormat

from mkt.api.exceptions import DeserializationError


class Serializer(Serializer):

    formats = ['json', 'urlencode']
    content_types = {
        'json': 'application/json',
        'urlencode': 'application/x-www-form-urlencoded',
    }

    def from_urlencode(self, data):
        return dict(parse_qsl(data))

    def to_urlencode(self, data, options=None):
        raise UnsupportedFormat

    def deserialize(self, content, format='application/json'):
        try:
            return super(Serializer, self).deserialize(content, format)
        except JSONDecodeError, exc:
            raise DeserializationError(original=exc)
