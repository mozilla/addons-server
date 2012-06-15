from jingo import register
from jinja2 import contextfunction

from reviews.models import GroupedRating


@register.inclusion_tag('ratings/helpers/rating_header.html')
@contextfunction
def rating_header(context, product, title):
    c = dict(context.items())
    c.update(product=product, title=title,
             grouped_ratings=GroupedRating.get(product.id))
    return c
