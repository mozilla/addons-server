from django.utils.encoding import force_unicode

from bleach import NODE_TEXT
import html5lib
import jinja2


def trim(tree, limit, killwords, end):
    """Truncate the text of an html5lib tree."""
    root = tree.cloneNode()
    length = 0
    for node in tree.childNodes:
        # Stop if we have enough characters.
        if length >= limit:
            break

        # We have a text node, so slurp up characters without going over.
        if node.type == NODE_TEXT:
            new = node.cloneNode()
            root.appendChild(new)
            text = new.value.strip()
            if len(text) + length < limit:
                length += len(text)
            else:
                # Don't let jinja add ``end`` because it doesn't know that
                # we're truncating up here.
                trunc = jinja2.filters.do_truncate(text, limit - length,
                                                       killwords, end='')
                new.value = trunc + end
                length = limit
        else:
            # Recurse on other non-text nodes.
            child, child_len = trim(node, limit - length, killwords, end)
            root.appendChild(child)
            length += child_len
    return root, length


def text_length(tree):
    """Find the length of the text content, excluding markup."""
    def walk(tree):
        if tree.type == NODE_TEXT:
            return len(tree.value.strip())
        else:
            return sum(walk(node) for node in tree.childNodes)
    return walk(tree)


def truncate(html, length, killwords=False, end='...'):
    """
    Return a slice of ``html`` <= length chars.

    killwords and end are currently ignored.

    ONLY USE FOR KNOWN-SAFE HTML.
    """
    tree = html5lib.parseFragment(html, encoding='utf-8')
    if text_length(tree) <= length:
        return jinja2.Markup(html)
    else:
        short, _ = trim(tree, length, killwords, end)
        return jinja2.Markup(force_unicode(short.toxml()))
