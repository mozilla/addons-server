from django.template import engines
from django.utils.encoding import force_text

import html5lib
import jinja2


def truncate_text(text, limit, killwords=False, end='...'):
    """Return as many characters as possible without going over the limit.

    Return the truncated text and the characters left before the limit, if any.

    """
    text = text.strip()
    text_length = len(text)

    if text_length < limit:
        return text, limit - text_length

    # Explicitly add "end" in any case, as Jinja can't know we're truncating
    # for real here, even though we might be at the end of a word.
    text = jinja2.filters.do_truncate(
        engines['jinja2'].env,
        text,
        length=limit,
        killwords=killwords,
        leeway=0,
        end='',
    )

    return text + end, 0


def trim(tree, limit, killwords, end):
    """Truncate the text of an html5lib tree."""
    if tree.text:  # Root node's text.
        tree.text, limit = truncate_text(tree.text, limit, killwords, end)
    for child in tree:  # Immediate children.
        if limit <= 0:
            # We reached the limit, remove all remaining children.
            tree.remove(child)
        else:
            # Recurse on the current child.
            _parsed_tree, limit = trim(child, limit, killwords, end)
    if tree.tail:  # Root node's tail text.
        if limit <= 0:
            tree.tail = ''
        else:
            tree.tail, limit = truncate_text(tree.tail, limit, killwords, end)
    return tree, limit


def text_length(tree):
    """Find the length of the text content, excluding markup."""
    total = 0
    for node in tree.getiterator():  # Traverse all the tree nodes.
        # In etree, a node has a text and tail attribute.
        # Eg: "<b>inner text</b> tail text <em>inner text</em>".
        if node.text:
            total += len(node.text.strip())
        if node.tail:
            total += len(node.tail.strip())
    return total


def truncate(html, length, killwords=False, end='...'):
    """
    Return a slice of ``html`` <= length chars.

    killwords and end are currently ignored.

    ONLY USE FOR KNOWN-SAFE HTML.
    """
    tree = html5lib.parseFragment(html)
    if text_length(tree) <= length:
        return jinja2.Markup(html)
    else:
        # Get a truncated version of the tree.
        short, _ = trim(tree, length, killwords, end)

        # Serialize the parsed tree back to html.
        walker = html5lib.treewalkers.getTreeWalker('etree')
        stream = walker(short)
        serializer = html5lib.serializer.htmlserializer.HTMLSerializer(
            quote_attr_values=True, omit_optional_tags=False
        )
        return jinja2.Markup(force_text(serializer.render(stream)))


def transfield_changed(field, initial, data):
    """
    For forms, compares initial data against cleaned_data for TransFields.
    Returns True if data is the same. Returns False if data is different.

    Arguments:
    field -- name of the form field as-is.
    initial -- data in the form of {'description_en-us': 'x',
                                    'description_en-br': 'y'}
    data -- cleaned data in the form of {'description': {'init': '',
                                                         'en-us': 'x',
                                                         'en-br': 'y'}
    """
    initial = [
        (k, v.localized_string)
        for k, v in initial.iteritems()
        if '%s_' % field in k and v is not None
    ]
    data = [
        ('%s_%s' % (field, k), v)
        for k, v in data[field].iteritems()
        if k != 'init'
    ]
    return set(initial) != set(data)
