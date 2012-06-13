from jingo import register
from jinja2 import contextfunction


@register.inclusion_tag('ratings/helpers/rating_header.html')
@contextfunction
def rating_header(context, product, title):
    c = dict(context.items())
    c.update(product=product, title=title)
    return c
