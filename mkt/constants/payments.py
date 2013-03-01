from tower import ugettext as _


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
