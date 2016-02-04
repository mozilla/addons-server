from django.contrib.syndication.views import Feed
from django.db.transaction import non_atomic_requests
from django.utils.decorators import method_decorator


class NonAtomicFeed(Feed):
    """
    A feed that does not use transactions.

    Feeds are special because they don't inherit from generic Django class
    views so you can't decorate dispatch().
    """

    @method_decorator(non_atomic_requests)
    def __call__(self, *args, **kwargs):
        return super(NonAtomicFeed, self).__call__(*args, **kwargs)
