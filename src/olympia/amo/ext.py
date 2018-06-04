import jinja2.runtime

from jinja2 import nodes
from jinja2.ext import Extension

from django.conf import settings
from django.utils.encoding import smart_str

from olympia.lib.cache import cache_get_or_set


class FragmentCacheExtension(Extension):
    """
    Cache a chunk of template code based on a queryset.  Since looping over
    querysets is the slowest thing we do, you should wrap you for loop with the
    cache tag.  Uses the default timeout unless you pass a second argument.

    {% cache queryset[, timeout] %}
      ...template code...
    {% endcache %}

    Derived from the jinja2 documentation example.
    """
    tags = set(['cache'])

    def __init__(self, environment):
        super(FragmentCacheExtension, self).__init__(environment)

    def preprocess(self, source, name, filename=None):
        self.name = filename or name
        return source

    def parse(self, parser):
        # the first token is the token that started the tag.  In our case
        # we only listen to ``'cache'`` so this will be a name token with
        # `cache` as value.  We get the line number so that we can give
        # that line number to the nodes we create by hand.
        lineno = next(parser.stream).lineno

        # Use the filename + line number and first object for the cache key.
        name = '%s+%s' % (self.name, lineno)
        args = [nodes.Const(name), parser.parse_expression()]

        # If there is a comma, the user provided a timeout.  If not, use
        # None as second parameter.
        timeout = nodes.Const(None)
        extra = nodes.Const([])
        while parser.stream.skip_if('comma'):
            x = parser.parse_expression()
            if parser.stream.current.type == 'assign':
                next(parser.stream)
                extra = parser.parse_expression()
            else:
                timeout = x
        args.extend([timeout, extra])

        body = parser.parse_statements(['name:endcache'], drop_needle=True)

        self.process_cache_arguments(args)

        # now return a `CallBlock` node that calls our _cache_support
        # helper method on this extension.
        return nodes.CallBlock(self.call_method('_cache_support', args),
                               [], [], body).set_lineno(lineno)

    def process_cache_arguments(self, args):
        args.append(nodes.Getattr(nodes.ContextReference(), 'request', 'load'))

    def _cache_support(self, name, obj, timeout, extra, request, caller):
        if isinstance(request, jinja2.runtime.Undefined):
            key = name
        else:
            if request.user.is_authenticated():
                return caller()
            else:
                key = '%s:%s' % (name, request.APP.id)

        if settings.DEBUG:
            return caller()
        extra = ':'.join(map(smart_str, extra))
        key = 'fragment:%s:%s' % (name, extra)
        return cache_get_or_set(key, caller, timeout=timeout)


cache = FragmentCacheExtension
