import jinja2

from django_jinja import library


@library.global_function
@library.render_with('tags/tag_list.html')
@jinja2.contextfunction
def tag_list(context, addon, tags=None):
    """Display list of tags, with delete buttons."""
    if tags is None:
        tags = []

    c = dict(context.items())
    c.update({'addon': addon, 'tags': tags})
    return c
