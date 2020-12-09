import jinja2

from django_jinja import library


@library.global_function
@library.render_with('addons/impala/listing/sorter.html')
@jinja2.contextfunction
def impala_addon_listing_header(
    context,
    url_base,
    sort_opts=None,
    selected=None,
    extra_sort_opts=None,
    search_filter=None,
):
    if sort_opts is None:
        sort_opts = {}
    if extra_sort_opts is None:
        extra_sort_opts = {}
    if search_filter:
        selected = search_filter.field
        sort_opts = search_filter.opts
        if hasattr(search_filter, 'extras'):
            extra_sort_opts = search_filter.extras
    # When an "extra" sort option becomes selected, it will appear alongside
    # the normal sort options.
    old_extras = extra_sort_opts
    sort_opts, extra_sort_opts = list(sort_opts), []
    for k, v in old_extras:
        if k == selected:
            sort_opts.append((k, v, True))
        else:
            extra_sort_opts.append((k, v))
    return new_context(**locals())


def new_context(context, **kw):
    c = dict(context.items())
    c.update(kw)
    return c
