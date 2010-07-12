from django.utils.html import escape

import jingo
import jinja2
from tower import ugettext_lazy as _

from . import forms


@jingo.register.function
def SearchForm(request):
    return forms.SearchForm(request)


@jingo.register.function
def pagination_result_count(pager):
    "Returns a 'Results m-n of y.'"
    format_opts = (pager.start_index(), pager.end_index(),
                   pager.paginator.count,)

    result_string = _(u'Results <strong>{0}</strong>-<strong>{1}</strong>'
                      ' of <strong>{2}</strong>').format(*format_opts)

    return jinja2.Markup(result_string)


@jingo.register.function
def showing(query, tag, pager):
    """Writes a string that tells the user what they are seeing in terms of
    search results."""
    format_opts = (pager.start_index(), pager.end_index(),
                   pager.paginator.count,)

    query = escape(query)
    tag = escape(tag)

    # TODO: Can we cleanly localize this, so we can do "Showing no results for
    # Foo tagged with Bar" without having more if/elif/else statements?

    if query and tag:
        showing = _(u'Showing {0} - {1} of {2} results for '
                '<strong>{3}</strong>'
                ' tagged with <strong>{4}</strong>').format(
                *(format_opts + (query, tag,)))
    elif query and not tag:
        showing = _(u'Showing {0} - {1} of {2} results for '
                    '<strong>{3}</strong>').format(*(format_opts + (query,)))
    elif not query and tag:
        showing = _(u'Showing {0} - {1} of {2} results tagged with '
                '<strong>{3}</strong>').format(*(format_opts + (tag,)))
    else:
        showing = _(u'Showing {0} - {1} of {2} results').format(*format_opts)

    return jinja2.Markup(showing)
