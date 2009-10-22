import jingo


def direct_to_template(request, template, **kwargs):
    return jingo.render(request, template, kwargs)
