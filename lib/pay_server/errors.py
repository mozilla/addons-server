# If you get a PayPal error, you'll get a PayPal error code back.
# This converts these into localisable strings we can give to the user.
from tower import ugettext as _

codes = {
    '0': _('There was an error with that request.'),
}


def lookup(code):
    # TODO(solitude): cope with different codes for different calls.
    # TODO(solitude): diffentiate between PayPal and BlueVia codes.
    return codes.get(str(code), codes.get('0'))
