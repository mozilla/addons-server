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


class SuggestionsSerializer(Serializer):
    formats = ['suggestions+json', 'json']
    content_types = {
        'suggestions+json': 'application/x-suggestions+json',
        'json': 'application/json',
    }

    def serialize(self, bundle, format='application/json', options=None):
        if options is None:
            options = {}
        if format == 'application/x-suggestions+json':
            # Format application/x-suggestions+json just like regular json.
            format = 'application/json'
        return super(SuggestionsSerializer, self).serialize(bundle,
                                                            format=format,
                                                            options=options)
