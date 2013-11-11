from ordereddict import OrderedDict

from tower import ugettext_lazy as _lazy


# WARNING: When adding a new interactive element here also include a migration.
#
# These are used to dynamically generate the field list for the
# RatingInteractives django model in mkt.webapps.models.
RATING_INTERACTIVES = OrderedDict([
    ('USERS_INTERACT', {
        'name': _lazy('Users Interact'),
    }),
    ('SHARES_INFO', {
        'name': _lazy('Shares Info'),
    }),
    ('SHARES_LOCATION', {
        'name': _lazy('Shares Location'),
    }),
    ('DIGITAL_PURCHASES', {
        'name': _lazy('Digital Purchases'),
    }),
    ('SOCIAL_NETWORKING', {
        'name': _lazy('Social Networking'),
    }),
    ('DIGITAL_CONTENT_PORTAL', {
        'name': _lazy('Digital Content Portal'),
    }),
])
