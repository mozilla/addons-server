import urllib

from django.conf import settings
from django.db.models import Model

from base import Client, Encoder, SolitudeError

client = None


def model_to_uid(model):
    return ':'.join((settings.DOMAIN.replace('-', '.'),
                     model.__class__._meta.db_table,
                     str(model.pk))).lower()


class ZamboniEncoder(Encoder):

    def default(self, v):
        if isinstance(v, Model):
            return model_to_uid(v)
        return super(ZamboniEncoder, self).default(v)


def filter_encoder(query):
    for k, v in query.items():
        if isinstance(v, Model):
            query[k] = model_to_uid(v)
    return urllib.urlencode(query)


class ZamboniClient(Client):
    Error = SolitudeError


def get_client():
    # If you haven't specified a solitude host, we can't do anything.
    if settings.SOLITUDE_HOSTS:
        config = {
            # TODO: when seclusion can cope with multiple hosts, we'll pass
            # them all through and let seclusion do its magic.
            'server': settings.SOLITUDE_HOSTS[0],
            'key': settings.SOLITUDE_KEY,
            'secret': settings.SOLITUDE_SECRET,
            'timeout': settings.SOLITUDE_TIMEOUT
        }
        client = ZamboniClient(config)
        client.encoder = ZamboniEncoder
        client.filter_encoder = filter_encoder
        return client

if not client:
    client = get_client()
