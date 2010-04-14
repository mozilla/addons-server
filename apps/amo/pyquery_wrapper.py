"""
If libxml2 finds a <noscript> element in <head>, it appears to create a <body>
block right there and drop our real <body>, which has nice attributes we'd like
to see.  So we'll regex out all those nasty <noscript>s and pretend everything
is just right.

The libxml2 bug is https://bugzilla.gnome.org/show_bug.cgi?id=615785.
"""
import re

import pyquery

# Yes, we're munging HTML with a regex.  Deal with it.
noscript_re = re.compile('<noscript>.*?</noscript>')

def remove_noscript_from_head(html):
    head_end = html.find('</head>')
    new_head = noscript_re.sub('', html[:head_end])
    return new_head + html[head_end:]


class PyQuery(pyquery.PyQuery):

    def __init__(self, *args, **kwargs):
        if (args and isinstance(args[0], basestring) and
            not args[0].startswith('http')):
            args = (remove_noscript_from_head(args[0]),) + args[1:]
        super(PyQuery, self).__init__(*args, **kwargs)
