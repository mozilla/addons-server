from django.http import QueryDict
from django.utils.simplejson import JSONDecodeError

import commonware.log
from rest_framework import serializers
from tastypie.serializers import Serializer
from tastypie.exceptions import UnsupportedFormat
from tower import ugettext as _

from mkt.api.exceptions import DeserializationError


log = commonware.log.getLogger('z.mkt.api.forms')


class Serializer(Serializer):

    formats = ['json', 'urlencode']
    content_types = {
        'json': 'application/json',
        'urlencode': 'application/x-www-form-urlencoded',
    }

    def from_urlencode(self, data):
        return QueryDict(data).dict()

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


class PotatoCaptchaSerializer(serializers.Serializer):
    """
    Serializer class to inherit from to get PotatoCaptcha (tm) protection for
    an API based on DRF.

    Clients using this API are supposed to have 2 fields in their HTML, "tuber"
    and "sprout". They should never submit a value for "tuber", and they should
    always submit "potato" as the value for "sprout". This is to prevent dumb
    bots from spamming us.

    If a wrong value is entered for "sprout" or "tuber" is present, a 
    ValidationError will be returned.

    Note: this is completely disabled for authenticated users.
    """

    # This field's value should always be blank (spammers are dumb).
    tuber = serializers.CharField(required=False)

    # This field's value should always be 'potato' (set by JS).
    sprout = serializers.CharField()

    def __init__(self, *args, **kwargs):
        super(PotatoCaptchaSerializer, self).__init__(*args, **kwargs)
        if hasattr(self, 'context') and 'request' in self.context:
            self.request = self.context['request']
        else:
            raise serializers.ValidationError('Need request in context')

        self.has_potato_recaptcha = True
        if self.request.user.is_authenticated():
            self.fields.pop('tuber')
            self.fields.pop('sprout')
            self.has_potato_recaptcha = False

    def validate(self, attrs):
        attrs = super(PotatoCaptchaSerializer, self).validate(attrs)
        if self.has_potato_recaptcha:
            sprout = attrs.get('sprout', None)
            tuber = attrs.get('tuber', None)

            if tuber or sprout != 'potato':
                ip = self.request.META.get('REMOTE_ADDR', '')
                log.info(u'Spammer thwarted: %s' % ip)
                raise serializers.ValidationError(
                    _('Form could not be submitted.'))

            # Don't keep the internal captcha fields, we don't want them to
            # pollute self.data
            self.fields.pop('tuber')
            self.fields.pop('sprout')
        return attrs
