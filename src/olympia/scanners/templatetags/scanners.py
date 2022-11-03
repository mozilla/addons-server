from django.utils.html import conditional_escape, format_html, format_html_join

from django import template
from django.urls import reverse

register = template.Library()


@register.filter
def format_scanners_data(data, parent=None):
    """HTML formatter for scanners data. Recognizes some specific keys but
    otherwise should be generic enough to work with any kind of data that can
    be returned by scanners.
    """
    if isinstance(data, list):
        rval = format_html(
            "<ul>\n{}\n</ul>",
            format_html_join(
                "\n", "<li>{}</li>", ((format_scanners_data(v),) for v in data)
            ),
        )
    elif isinstance(data, dict):
        rval = format_html(
            "<dl>\n{}\n</dl>",
            format_html_join(
                "\n",
                "<dt>{}:</dt><dd>{}</dd>",
                (
                    (format_scanners_data(k), format_scanners_data(v, parent=k))
                    for k, v in data.items()
                ),
            ),
        )
    elif isinstance(data, (float, int)):
        if parent == 'ratio':
            rval = f"{data * 100:.2f}%"
        else:
            rval = str(round(data, 3))
    else:
        if parent == 'extensionId':
            url = reverse('reviewers.review', args=[data])
            rval = format_html('<a href="{}">{}</a>', url, data)
        else:
            rval = conditional_escape(data)
    return rval
