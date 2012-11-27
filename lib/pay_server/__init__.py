import hashlib
import urllib
import uuid

from django.conf import settings
from django.db.models import Model

from base import Client, Encoder, SolitudeError
from errors import pre_approval_codes

from amo.helpers import absolutify, urlparams
from amo.urlresolvers import reverse

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

    def lookup_buyer_paypal(self, buyer):
        res = self.get_buyer(filters={'uuid': buyer})
        count = res['meta']['total_count']
        if count == 1:
            return res['objects'][0]['paypal']
        else:
            raise ValueError('Get returned %s buyers.' % count)

    def create_buyer_if_missing(self, buyer):
        """
        Checks to see if the buyer exists in solitude. If not we'll create
        it so that solitude can store the pre-approval data for that buyer.
        """
        res = self.get_buyer(filters={'uuid': buyer})
        if res['meta']['total_count'] == 0:
            self.post_buyer(data={'uuid': buyer})

    def get_seller_paypal_if_exists(self, seller):
        """
        Will return the paypal details if the user and paypal data exists.
        """
        res = self.get_seller(filters={'uuid': seller})
        if res['meta']['total_count'] == 1:
            return res['objects'][0]['paypal']

    def create_seller_paypal(self, seller):
        """
        Will see if the user exists. If it does, will see if paypal exists, if
        it doesn't it will create a paypal record. It will then return the
        paypal pk, so we can do calls to it.
        """
        res = self.get_seller(filters={'uuid': seller})
        count = res['meta']['total_count']
        if count == 0:
            # There's no seller data, so create the seller objects.
            sel = self.post_seller(data={'uuid': seller})
            return self.post_seller_paypal(data={'seller':
                                                 sel['resource_uri']})
        elif count == 1:
            sel = res['objects'][0]
            paypal = sel['paypal']
            if not paypal:
                # There is no PayPal object. Create one.
                return self.post_seller_paypal(data={'seller':
                                                     sel['resource_uri']})
            # The resource_pk is there in the first results, just save it.
            return paypal
        else:
            raise ValueError('Get returned %s sellers.' % count)

    def create_seller_for_pay(self, addon):
        """
        A temporary method to populate seller data, when a data migration
        is completed, this can be removed.
        """
        obj = client.create_seller_paypal(addon)
        if not obj['paypal_id']:
            client.patch_seller_paypal(pk=obj['resource_pk'],
                                       data={'paypal_id': addon.paypal_id})

        return obj['resource_pk']

    def make_uuid(self):
        return hashlib.md5(str(uuid.uuid4())).hexdigest()

    def make_urls(self, data):
        uuid = self.make_uuid()
        seller = data['seller']
        # If the pay call doesn't specify complete URLs, use some defaults.
        if 'complete' not in data:
            data['complete'] = urlparams(
                    seller.get_purchase_url(action='done', args=['complete']),
                    uuid=uuid)
        if 'cancel' not in data:
            data['cancel'] = urlparams(
                    seller.get_purchase_url(action='done', args=['cancel']),
                    uuid=uuid)
        # Absolutify all URLs. Absolutify can safely be called multiple
        # times with no ill effects.
        return {
            'cancel_url': absolutify(data['cancel']),
            'return_url': absolutify(data['complete']),
            'ipn_url': absolutify(reverse('amo.paypal')),
            'uuid': uuid
        }

    def pay(self, payload, retry=True):
        """
        Add in uuid and urls on the way. If retry is True, if the transaction
        fails because of a pre-approval failure, we'll try it a second time
        without it.
        """
        data = payload.copy()
        data.update(self.make_urls(payload))
        data['use_preapproval'] = True

        try:
            return self.post_pay(data=data)
        except self.Error, error:
            if not (retry and error.code in pre_approval_codes):
                raise

        data.update(self.make_urls(payload))
        data['use_preapproval'] = False
        return self.post_pay(data=data)

    def prepare_bluevia_pay(self, data):
        """
        Return a JWT for BlueVia's navigator.pay() to purchase an app on B2G.
        """
        return self.post_prepare_bluevia_pay(data=data)

    def verify_bluevia_jwt(self, bluevia_jwt):
        """
        Verify signature of BlueVia JWT for developer ID (via JWT aud)
        """
        # Use Solitude for verification. bug 777936
        return self.post_verify_bluevia_jwt(data={'bluevia_jwt': bluevia_jwt})


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
