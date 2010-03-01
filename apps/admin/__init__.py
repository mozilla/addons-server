from django.contrib.admin import options, actions, sites
from django.template import loader

import jingo


def django_to_jinja(template_name, context, **kw):
    """
    We monkeypatch Django admin's render_to_response to work in our Jinja
    environment.  We have an admin/base_site.html template that Django's
    templates inherit, but instead of rendering html, it renders the Django
    pieces into a Jinja template.  We get all of Django's html, but wrapped in
    our normal site structure.
    """
    context_instance = kw.pop('context_instance')
    source = loader.render_to_string(template_name, context, context_instance)
    request = context_instance['request']
    return jingo.render(request, jingo.env.from_string(source))

actions.render_to_response = django_to_jinja
options.render_to_response = django_to_jinja
sites.render_to_response = django_to_jinja
