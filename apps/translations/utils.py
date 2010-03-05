from django.utils.encoding import force_unicode
from bleach import NODE_TEXT
import html5lib
import jinja2


parser = html5lib.HTMLParser()


def text_length(html):
    """Find the length of the text content, excluding markup."""
    def walk(tree):
        if tree.type == NODE_TEXT:
            return len(tree.value.strip())
        else:
            return sum(walk(node) for node in tree.childNodes)
    return walk(parser.parseFragment(html, encoding='utf-8'))


def _truncate(html, length):
    # Binary search could drop us in the middle of a tag, but it's close
    # enough.
    if text_length(html) <= length:
        return html

    hi, lo = len(html), 0
    while hi > lo:
        mid = (hi + lo) / 2
        _len = text_length(html[:mid])
        if _len < length:
            lo = mid + 1
        elif _len > length:
            hi = mid - 1
        else:
            return html[:mid]
    return html[:mid]


def truncate(html, length, killwords=False, end='...'):
    """
    Return a slice of ``html`` <= length chars.

    killwords and end are currently ignored.
    """
    if text_length(html) <= length:
        return jinja2.Markup(html)

    short = _truncate(html.strip(), length)
    new = parser.parseFragment(short, encoding='utf-8').toxml()
    return jinja2.Markup(force_unicode(new) + end)
