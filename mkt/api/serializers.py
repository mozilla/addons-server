from urlparse import parse_qsl

from tastypie.serializers import Serializer
from tastypie.exceptions import UnsupportedFormat


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
