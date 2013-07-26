from tower import ugettext_lazy as _lazy


COLLECTIONS_TYPE_BASIC = 0
COLLECTIONS_TYPE_FEATURED = 1
COLLECTIONS_TYPE_OPERATOR = 2

COLLECTION_TYPES = (
    (COLLECTIONS_TYPE_BASIC, _lazy(u'Basic Collection')),
    (COLLECTIONS_TYPE_FEATURED, _lazy(u'Featured App List')),
    (COLLECTIONS_TYPE_OPERATOR, _lazy(u'Operator Shelf')),
)
