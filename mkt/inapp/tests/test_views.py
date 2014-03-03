import json

from django.contrib.auth.models import User
from django.core.urlresolvers import reverse

from nose.tools import eq_
from rest_framework import status

import amo.tests
from market.models import Price
from mkt.api.tests.test_oauth import RestOAuthClient
from mkt.api.models import Access, generate
from mkt.inapp.models import InAppProduct
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp


class BaseInAppProductViewSetTests(amo.tests.TestCase):
    def setUp(self):
        self.webapp = Webapp.objects.get(pk=337141)
        price = Price.objects.all()[0]
        self.valid_in_app_product_data = {
            'name': 'Purple Gems',
            'logo_url': 'https://marketplace.firefox.com/rocket.png',
            'price_id': price.id,
        }

    def setup_client(self, user):
        access = Access.objects.create(key='test_oauth_key_owner',
                                       secret=generate(), user=user)
        return RestOAuthClient(access)

    def list_url(self):
        return reverse('in-app-products-list',
                       kwargs={'app_slug': self.webapp.app_slug})

    def detail_url(self, pk):
        app_slug = self.webapp.app_slug
        return reverse('in-app-products-detail',
                       kwargs={'app_slug': app_slug, 'pk': pk})

    def create_product(self):
        product_data = {'webapp': self.webapp}
        product_data.update(self.valid_in_app_product_data)
        return InAppProduct.objects.create(**product_data)


class TestInAppProductViewSetAuthorized(BaseInAppProductViewSetTests):
    fixtures = fixture('webapp_337141', 'prices')

    def setUp(self):
        super(TestInAppProductViewSetAuthorized, self).setUp()
        user = self.webapp.authors.all()[0].user
        self.client = self.setup_client(user)

    def test_create(self):
        response = self.client.post(self.list_url(),
                                    json.dumps(self.valid_in_app_product_data),
                                    content_type='application/json')
        eq_(response.status_code, status.HTTP_201_CREATED)
        eq_(response.json['name'], 'Purple Gems')

    def test_update(self):
        product = self.create_product()
        self.valid_in_app_product_data['name'] = 'Orange Gems'
        response = self.client.put(self.detail_url(product.id),
                                   json.dumps(self.valid_in_app_product_data),
                                   content_type='application/json')
        eq_(response.status_code, status.HTTP_200_OK)
        eq_(response.json['name'], 'Orange Gems')
        eq_(response.json['name'], product.reload().name)

    def test_list(self):
        product1 = self.create_product()
        product2 = self.create_product()
        response = self.client.get(self.list_url())
        eq_(response.status_code, status.HTTP_200_OK)
        eq_(sorted([p['id'] for p in response.json['objects']]),
            [product1.id, product2.id])

    def test_detail(self):
        product = self.create_product()
        response = self.client.get(self.detail_url(product.id))
        eq_(response.status_code, status.HTTP_200_OK)
        eq_(response.json['id'], product.id)

    def test_delete(self):
        product = self.create_product()
        delete_response = self.client.delete(self.detail_url(product.id))
        eq_(delete_response.status_code, status.HTTP_403_FORBIDDEN)


class TestInAppProductViewSetUnauthorized(BaseInAppProductViewSetTests):
    fixtures = fixture('user_999', 'webapp_337141', 'prices')

    def setUp(self):
        super(TestInAppProductViewSetUnauthorized, self).setUp()
        user = User.objects.get(id=999)
        self.client = self.setup_client(user)

    def test_create(self):
        response = self.client.post(self.list_url(),
                                    json.dumps(self.valid_in_app_product_data),
                                    content_type='application/json')
        eq_(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_update(self):
        product = self.create_product()
        self.valid_in_app_product_data['name'] = 'Orange Gems'
        response = self.client.put(self.detail_url(product.id),
                                   json.dumps(self.valid_in_app_product_data),
                                   content_type='application/json')
        eq_(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list(self):
        self.create_product()
        response = self.client.get(self.list_url())
        eq_(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_detail(self):
        product = self.create_product()
        response = self.client.get(self.detail_url(product.id))
        eq_(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete(self):
        product = self.create_product()
        response = self.client.delete(self.detail_url(product.id))
        eq_(response.status_code, status.HTTP_403_FORBIDDEN)
