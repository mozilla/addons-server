# If you get a PayPal error, you'll get a PayPal error code back.
# This converts these into localisable strings we can give to the user.
from tower import ugettext as _

# Codes:
# - starting with 100000+ are solitude specific codes.
# - starting with 500000+ are paypal specific codes.
codes = {
    '0': _('There was an error with that request.'),
    # The personal data returned did not match the paypal id specified.
    # This message is defined in solitude, so just pass it through.
    '100001': _('The email returned by Paypal, did not match the PayPal '
                'email you entered. Please login using %(email)s.'),
}


def lookup(code, data):
    return codes.get(str(code), codes.get('0')) % data
