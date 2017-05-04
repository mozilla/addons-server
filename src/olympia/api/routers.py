from rest_framework.routers import SimpleRouter


class OptionalLookupRouter(SimpleRouter):
    """Wraps the lookup_regex to make it optional in url patterns."""

    def get_lookup_regex(self, viewset, lookup_prefix=''):
        regex = super(OptionalLookupRouter, self).get_lookup_regex(
            viewset, lookup_prefix)
        return '(?:%s)?' % regex
