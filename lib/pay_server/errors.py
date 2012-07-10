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

# See the PayPal docs for information on these codes: http://bit.ly/vWV525
pre_approval_codes = ['539012', '569013', '569016', '569017', '569018',
                      '569019', '579010', '579014', '579024', '579025',
                      '579026', '579027', '579028', '579030', '579031',
                      '589019']
