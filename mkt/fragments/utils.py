import json
import types
from django.utils.encoding import smart_unicode


def bust_fragments(response, prefix, *args, **kwargs):
    """Bust the fragments cache where the URLs match `prefix`.

    `response`
        A Django response object.
    `prefix`
        A string or list of strings containing URL prefixes to bust.
    `args`
        A list of string-castable values which will be used for positional
        formatting into each of the prefix strings.
    `kwargs`
        A dict of string-castable values which will be used for keyword
        formatting into each of the prefix strings.
    """

    if isinstance(prefix, types.StringTypes):
        prefix = [prefix]

    def reformat_prefix(prefix):
        # If the prefix needs no formatting, bail out.
        if '{' not in prefix or '}' not in prefix:
            return prefix
        return smart_unicode(prefix).format(*args, **kwargs)

    if args or kwargs:
        # Reformat each of the prefixes accordingly.
        prefix = map(reformat_prefix, prefix)

    # TODO: When we need it, we should be detecting existing `fcbust` cookies
    # and including them in the new flag (removing duplicates/overridden URL
    # prefixes).

    # Encode the list of prefixes as JSON.
    prefix = json.dumps(prefix)

    # At this point, we know we're busting the fragment cache.
    response['x-frag-bust'] = prefix
