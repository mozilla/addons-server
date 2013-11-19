from tower import ugettext_lazy as _
from mkt.constants.bango import BANGO_CURRENCIES_KEYS


# Paypal is an awful place that doesn't understand locales.  Instead they have
# country codes.  This maps our locales to their codes.
PAYPAL_COUNTRYMAP = {
    'af': 'ZA', 'ar': 'EG', 'ca': 'ES', 'cs': 'CZ', 'cy': 'GB', 'da': 'DK',
    'de': 'DE', 'de-AT': 'AT', 'de-CH': 'CH', 'el': 'GR', 'en-GB': 'GB',
    'eu': 'BS', 'fa': 'IR', 'fi': 'FI', 'fr': 'FR', 'he': 'IL', 'hu': 'HU',
    'id': 'ID', 'it': 'IT', 'ja': 'JP', 'ko': 'KR', 'mn': 'MN', 'nl': 'NL',
    'pl': 'PL', 'ro': 'RO', 'ru': 'RU', 'sk': 'SK', 'sl': 'SI', 'sq': 'AL',
    'sr': 'CS', 'tr': 'TR', 'uk': 'UA', 'vi': 'VI',
}

# Source, PayPal docs, PP_AdaptivePayments.PDF
PAYPAL_CURRENCIES = {
    'AUD': _('Australian Dollar'),
    'BRL': _('Brazilian Real'),
    'CAD': _('Canadian Dollar'),
    'CZK': _('Czech Koruna'),
    'DKK': _('Danish Krone'),
    'EUR': _('Euro'),
    'HKD': _('Hong Kong Dollar'),
    'HUF': _('Hungarian Forint'),
    'ILS': _('Israeli New Sheqel'),
    'JPY': _('Japanese Yen'),
    'MYR': _('Malaysian Ringgit'),
    'MXN': _('Mexican Peso'),
    'NOK': _('Norwegian Krone'),
    'NZD': _('New Zealand Dollar'),
    'PHP': _('Philippine Peso'),
    'PLN': _('Polish Zloty'),
    'GBP': _('Pound Sterling'),
    'SGD': _('Singapore Dollar'),
    'SEK': _('Swedish Krona'),
    'CHF': _('Swiss Franc'),
    'TWD': _('Taiwan New Dollar'),
    'THB': _('Thai Baht'),
    'USD': _('U.S. Dollar'),
}

OTHER_CURRENCIES = PAYPAL_CURRENCIES.copy()
del OTHER_CURRENCIES['USD']

# TODO(Kumar) bug 768223. Need to find a more complete list for this.
# This is just a sample.
LOCALE_CURRENCY = {
    'en_US': 'USD',
    'en_CA': 'CAD',
    'it': 'EUR',
    'fr': 'EUR',
    'pt_BR': 'BRL',
}

CURRENCY_DEFAULT = 'USD'

CONTRIB_VOLUNTARY = 0
CONTRIB_PURCHASE = 1
CONTRIB_REFUND = 2
CONTRIB_CHARGEBACK = 3
# We've started a transaction and we need to wait to see what
# paypal will return.
CONTRIB_PENDING = 4
# The following in-app contribution types are deprecated. Avoid re-using
# these ID numbers in new types.
_CONTRIB_INAPP_PENDING = 5
_CONTRIB_INAPP = 6
# The app was temporarily free. This is so we can record it in
# the purchase table, even though there isn't a contribution.
CONTRIB_NO_CHARGE = 7
CONTRIB_OTHER = 99

CONTRIB_TYPES = {
    CONTRIB_CHARGEBACK: _('Chargeback'),
    CONTRIB_OTHER: _('Other'),
    CONTRIB_PURCHASE: _('Purchase'),
    CONTRIB_REFUND: _('Refund'),
    CONTRIB_VOLUNTARY: _('Voluntary'),
}

MKT_TRANSACTION_CONTRIB_TYPES = {
    CONTRIB_CHARGEBACK: _('Chargeback'),
    CONTRIB_PURCHASE: _('Purchase'),
    CONTRIB_REFUND: _('Refund'),
}

CONTRIB_TYPE_DEFAULT = CONTRIB_VOLUNTARY

PAYPAL_PERSONAL = {
    'first_name': 'http://axschema.org/namePerson/first',
    'last_name': 'http://axschema.org/namePerson/last',
    'email': 'http://axschema.org/contact/email',
    'full_name': 'http://schema.openid.net/contact/fullname',
    'company': 'http://openid.net/schema/company/name',
    'country': 'http://axschema.org/contact/country/home',
    'payerID': 'https://www.paypal.com/webapps/auth/schema/payerID',
    'post_code': 'http://axschema.org/contact/postalCode/home',
    'address_one': 'http://schema.openid.net/contact/street1',
    'address_two': 'http://schema.openid.net/contact/street2',
    'city': 'http://axschema.org/contact/city/home',
    'state': 'http://axschema.org/contact/state/home',
    'phone': 'http://axschema.org/contact/phone/default'
}
PAYPAL_PERSONAL_LOOKUP = dict([(v, k) for k, v
                                      in PAYPAL_PERSONAL.iteritems()])

REFUND_PENDING = 0  # Just to irritate you I didn't call this REFUND_REQUESTED.
REFUND_APPROVED = 1
REFUND_APPROVED_INSTANT = 2
REFUND_DECLINED = 3
REFUND_FAILED = 4

REFUND_STATUSES = {
    # Refund pending (purchase > 30 min ago).
    REFUND_PENDING: _('Pending'),

    # Approved manually by developer.
    REFUND_APPROVED: _('Approved'),

    # Instant refund (purchase <= 30 min ago).
    REFUND_APPROVED_INSTANT: _('Approved Instantly'),

    # Declined manually by developer.
    REFUND_DECLINED: _('Declined'),

    #Refund didn't work somehow.
    REFUND_FAILED: _('Failed'),
}

PAYMENT_DETAILS_ERROR = {
    'CREATED': _('The payment was received, but not completed.'),
    'INCOMPLETE': _('The payment was received, but not completed.'),
    'ERROR': _('The payment failed.'),
    'REVERSALERROR': _('The reversal failed.'),
    'PENDING': _('The payment was received, but not completed '
                 'and is awaiting processing.'),
}

PROVIDER_PAYPAL = 0
PROVIDER_BANGO = 1
PROVIDER_REFERENCE = 2

PROVIDER_CHOICES = (
    (PROVIDER_PAYPAL, 'paypal'),
    (PROVIDER_BANGO, 'bango'),
    (PROVIDER_REFERENCE, 'reference')
)

PROVIDER_LOOKUP = dict([(v, k) for k, v in PROVIDER_CHOICES])
CARRIER_CHOICES = ()

# Payment methods accepted by the PriceCurrency..
#
# If we ever go beyond these two payment methods, we might need to do
# something more scalable.
PAYMENT_METHOD_OPERATOR = 0
PAYMENT_METHOD_CARD = 1
PAYMENT_METHOD_ALL = 2

PAYMENT_METHOD_CHOICES = (
    (PAYMENT_METHOD_OPERATOR, 'operator'),
    (PAYMENT_METHOD_CARD, 'card'),
    (PAYMENT_METHOD_ALL, 'operator+card')
)
