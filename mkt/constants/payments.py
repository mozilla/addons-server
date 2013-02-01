from tower import ugettext_lazy as _lazy


PROVIDER_PAYPAL = 0
PROVIDER_BANGO = 1

PROVIDERS = {
    PROVIDER_PAYPAL: _lazy('PayPal'),
    PROVIDER_BANGO: _lazy('Bango'),
}
