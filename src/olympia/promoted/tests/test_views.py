import stripe

from unittest import mock

from olympia.amo.tests import (
    APITestClient,
    TestCase,
    reverse_ns,
)


class TestStripeWebhook(TestCase):
    client_class = APITestClient

    def setUp(self):
        super().setUp()

        self.url = reverse_ns('promoted.stripe_webhook', api_version='v5')

    def test_invalid_http_method(self):
        response = self.client.get(self.url)

        assert response.status_code == 405

    @mock.patch('olympia.promoted.views.create_stripe_webhook_event')
    def test_invalid_signature(self, create_mock):
        create_mock.side_effect = stripe.error.SignatureVerificationError(
            message='error', sig_header=''
        )

        response = self.client.post(self.url)

        assert response.status_code == 400

    @mock.patch('olympia.promoted.views.create_stripe_webhook_event')
    def test_invalid_payload(self, create_mock):
        create_mock.side_effect = ValueError()

        response = self.client.post(self.url)

        assert response.status_code == 400

    @mock.patch('olympia.promoted.views.create_stripe_webhook_event')
    def test_event_received(self, create_mock):
        create_mock.return_value = mock.MagicMock(type='some-stripe-type')
        payload = b'some payload'
        sig_header = 'some signature'

        response = self.client.post(
            self.url,
            data=payload,
            content_type='text/plain',
            HTTP_STRIPE_SIGNATURE=sig_header,
        )

        assert response.status_code == 202
        create_mock.assert_called_once_with(payload=payload, sig_header=sig_header)

    @mock.patch('olympia.promoted.views.on_stripe_charge_failed.delay')
    @mock.patch('olympia.promoted.views.create_stripe_webhook_event')
    def test_charge_failed(self, create_mock, task_mock):
        fake_event = mock.MagicMock(type='charge.failed')
        create_mock.return_value = fake_event

        response = self.client.post(self.url)

        assert response.status_code == 202
        task_mock.assert_called_once_with(event=fake_event)

    @mock.patch('olympia.promoted.views.on_stripe_customer_subscription_deleted.delay')
    @mock.patch('olympia.promoted.views.create_stripe_webhook_event')
    def test_customer_subscription_deleted(self, create_mock, task_mock):
        fake_event = mock.MagicMock(type='customer.subscription.deleted')
        create_mock.return_value = fake_event

        response = self.client.post(self.url)

        assert response.status_code == 202
        task_mock.assert_called_once_with(event=fake_event)

    @mock.patch('olympia.promoted.views.on_stripe_charge_succeeded.delay')
    @mock.patch('olympia.promoted.views.create_stripe_webhook_event')
    def test_charge_succeeded(self, create_mock, task_mock):
        fake_event = mock.MagicMock(type='charge.succeeded')
        create_mock.return_value = fake_event

        response = self.client.post(self.url)

        assert response.status_code == 202
        task_mock.assert_called_once_with(event=fake_event)
