import datetime
import decimal
import json
import logging
import urllib

from django.conf import settings

from curling.lib import API

from tower import ugettext_lazy as _


log = logging.getLogger('s.client')


class SolitudeError(Exception):

    def __init__(self, *args, **kwargs):
        self.code = kwargs.pop('code', 0)
        super(SolitudeError, self).__init__(*args, **kwargs)


class SolitudeOffline(SolitudeError):
    pass


class SolitudeTimeout(SolitudeError):
    pass

date_format = '%Y-%m-%d'
time_format = '%H:%M:%S'


class Encoder(json.JSONEncoder):

    ENCODINGS = {
        datetime.datetime:
            lambda v: v.strftime('%s %s' % (date_format, time_format)),
        datetime.date: lambda v: v.strftime(date_format),
        datetime.time: lambda v: v.strftime(time_format),
        decimal.Decimal: str,
    }

    def default(self, v):
        """Encode some of our basic types in ways solitude understands."""
        return self.ENCODINGS.get(type(v), super(Encoder, self).default)(v)


general_error = _('Oops, we had an error processing that.')


class Client(object):

    def __init__(self, config=None):
        self.config = self.parse(config)
        self.api = API(config['server'])
        self.api.activate_oauth(settings.SOLITUDE_OAUTH.get('key'),
                                settings.SOLITUDE_OAUTH.get('secret'))
        self.encoder = None
        self.filter_encoder = urllib.urlencode

    def parse(self, config=None):
        return {'server': config.get('server')}
