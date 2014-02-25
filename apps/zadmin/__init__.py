from django.template import loader
from django.template.response import SimpleTemplateResponse

import jingo


def jinja_for_django(template_name, context=None, **kw):
    """
    If you want to use some built in logic (or a contrib app) but need to
    override the templates to work with Jinja, replace the object's
    render_to_response function with this one.  That will render a Jinja
    template through Django's functions.  An example can be found in the users
    app.
    """
    if context is None:
        context = {}
    context_instance = kw.pop('context_instance')
    request = context_instance['request']
    for d in context_instance.dicts:
        context.update(d)
    return jingo.render(request, template_name, context, **kw)


# We monkeypatch SimpleTemplateResponse.rendered_content to use our jinja
# rendering pipeline (most of the time). The exception is the admin app, where
# we render their Django templates and pipe the result through jinja to render
# our page skeleton.
def rendered_content(self):
    template = self.template_name
    context_instance = self.resolve_context(self.context_data)
    request = context_instance['request']

    # Gross, let's figure out if we're in the admin.
    if self._current_app == 'admin':
        source = loader.render_to_string(template, context_instance)
        template = jingo.env.from_string(source)
        # This interferes with our media() helper.
        if 'media' in self.context_data:
            del self.context_data['media']

    return jingo.render_to_string(request, template, self.context_data)

SimpleTemplateResponse.rendered_content = property(rendered_content)
