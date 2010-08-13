import jinja2.runtime
from jinja2 import nodes

import caching.ext


class FragmentCacheExtension(caching.ext.FragmentCacheExtension):
    """Extends the default fragment cache to include request.APP in the key."""

    def process_cache_arguments(self, args):
        args.append(nodes.Getattr(nodes.ContextReference(), 'request', 'load'))

    def _cache_support(self, name, obj, timeout, extra, request, caller):
        if isinstance(request, jinja2.runtime.Undefined):
            key = name
        else:
            key = '%s:%s' % (name, request.APP.id)
        sup = super(FragmentCacheExtension, self)._cache_support
        return sup(key, obj, timeout, extra, caller)


cache = FragmentCacheExtension
