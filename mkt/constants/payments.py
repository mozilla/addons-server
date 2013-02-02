from tower import ugettext_lazy as _lazy


STATUS_PENDING = 0  # When the payment has been started.
STATUS_COMPLETED = 1  # When the IPN says its ok.
STATUS_CHECKED = 2  # When someone calls pay-check on the transaction.
# When we we've got a request for a payment, but more work needs to be done
# before we can proceed to the next stage, pending.
STATUS_RECEIVED = 3
# Something went wrong and this transaction failed completely.
STATUS_FAILED = 4
# Explicit cancel action.
STATUS_CANCELLED = 5

STATUS_DEFAULT = STATUS_PENDING


PROVIDER_PAYPAL = 0
PROVIDER_BANGO = 1

PROVIDERS = {
    PROVIDER_PAYPAL: _lazy('PayPal'),
    PROVIDER_BANGO: _lazy('Bango'),
}
