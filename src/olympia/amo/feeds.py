import re

from django.contrib.syndication.views import Feed
from django.db.transaction import non_atomic_requests
from django.utils.decorators import method_decorator


class BaseFeed(Feed):
    """
    A base feed class that does not use transactions and tries to avoid raising
    exceptions on unserializable content.
    """
    # Regexp controlling which characters to strip from the items because they
    # would raise UnserializableContentError. Pretty much all control chars
    # except things like line feed, carriage return etc which are fine.
    CONTROL_CHARS_REGEXP = r'[\x00-\x08\x0B-\x0C\x0E-\x1F]'

    # Feeds are special because they don't inherit from generic Django class
    # views so you can't decorate dispatch() to add non_atomic_requests
    # decorator.
    @method_decorator(non_atomic_requests)
    def __call__(self, *args, **kwargs):
        return super(BaseFeed, self).__call__(*args, **kwargs)

    # When the feed is being built we go through this method for each attribute
    # we're returning, so we can use it to strip XML control chars before they
    # are being used. This avoid raising UnserializableContentError later.
    def _get_dynamic_attr(self, attname, obj, default=None):
        data = super(BaseFeed, self)._get_dynamic_attr(
            attname, obj, default=default)

        # Limite the search to the item types we know can potentially contain
        # some weird characters.
        problematic_keys = (
            'author_name',
            'comments',
            'description',
            'item_author_name',
            'item_description',
            'item_title',
            'title'
        )
        if data and attname in problematic_keys:
            data = re.sub(self.CONTROL_CHARS_REGEXP, '', unicode(data))
        return data
