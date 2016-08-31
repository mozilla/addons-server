import jingo

from django.template import loader, RequestContext
from django.template.backends.django import Template
from django.template.response import SimpleTemplateResponse

# We monkeypatch SimpleTemplateResponse.rendered_content to use our jinja
# rendering pipeline (most of the time). The exception is the admin app, where
# we render their Django templates and pipe the result through jinja to render
# our page skeleton.


def rendered_content(self):
    template = self.template_name

    if 'user' not in self.context_data:
        self.context_data['user'] = self._request.user

    context_instance = self.resolve_context(self.context_data)

    # Gross, let's figure out if we're in the admin.
    if getattr(self._request, 'current_app', None) == 'admin':
        source = loader.render_to_string(
            template, RequestContext(self._request, context_instance))
        template = jingo.get_env().from_string(source)

        # This interferes with our media() helper.
        if 'media' in self.context_data:
            del self.context_data['media']

    # ``render_to_string`` only accepts a Template instance or a template name,
    # not a list.
    if isinstance(template, (list, tuple)):
        template = loader.select_template(template)
    if isinstance(template, Template):
        template = template.template
    return jingo.render_to_string(
        self._request, template, self.context_data)


SimpleTemplateResponse.rendered_content = property(rendered_content)
