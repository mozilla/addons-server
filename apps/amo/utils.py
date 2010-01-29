import functools

from django.core import paginator


def paginate(request, queryset, per_page=20):
    """Get a Paginator, abstracting some common paging actions."""
    p = paginator.Paginator(queryset, per_page)

    # Get the page from the request, make sure it's an int.
    try:
        page = int(request.GET.get('page', 1))
    except ValueError:
        page = 1

    # Get a page of results, or the first page if there's a problem.
    try:
        paginated = p.page(page)
    except (paginator.EmptyPage, paginator.InvalidPage):
        paginated = p.page(1)

    paginated.add_query = functools.partial(add_query, request)
    return paginated


def add_query(request, **kwargs):
    """Return absolute url to current page with ``kwargs`` added to GET."""
    base = request.build_absolute_uri(request.path)
    query = dict(request.GET)
    query.update(kwargs)
    return '%s?%s' % (base, '&'.join('%s=%s' % q for q in query.items()))
