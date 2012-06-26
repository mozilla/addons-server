from django.conf import settings
from django.db.models import Model

from seclusion.base import Client, Encoder, SolitudeError

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


class ZamboniClient(Client):

    Error = SolitudeError

    def create_buyer_if_missing(self, buyer):
        """
        Checks to see if the buyer exists in solitude. If not we'll create
        it so that solitude can store the pre-approval data for that buyer.
        """
        res = self.get_buyer(filters={'uuid': model_to_uid(buyer)})
        if res['meta']['total_count'] == 0:
            self.post_buyer(data={'uuid': buyer})


def get_client():
    # If you haven't specified a seclusion host, we can't do anything.
    if settings.SECLUSION_HOSTS:
        config = {
            # TODO: when seclusion can cope with multiple hosts, we'll pass
            # them all through and let seclusion do its magic.
            'server': settings.SECLUSION_HOSTS[0],
            'key': settings.SECLUSION_KEY,
            'secret': settings.SECLUSION_SECRET
        }
        client = ZamboniClient(config)
        client.encoder = ZamboniEncoder
        return client

if not client:
    client = get_client()
