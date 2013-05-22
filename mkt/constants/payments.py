from tower import ugettext as _

MINIMUM_PRICE_FOR_NON_CARRIER_BILLING = 0.99

PENDING = 'PENDING'
COMPLETED = 'OK'
FAILED = 'FAILED'
REFUND_STATUSES = {
    PENDING: _('Pending'),
    COMPLETED: _('Completed'),
    FAILED: _('Failed'),
}

# SellerProduct access types.
ACCESS_PURCHASE = 1
ACCESS_SIMULATE = 2
