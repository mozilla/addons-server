from rest_framework.renderers import (JSONRenderer as BaseJSONRenderer,
                                      XMLRenderer)

from amo.utils import JSONEncoder

from .views import render_xml_to_string


class JSONRenderer(BaseJSONRenderer):

    encoder_class = JSONEncoder


class XMLTemplateRenderer(XMLRenderer):
    """
    Renders an XML template. Supports `template_name` kwargs from `Response`
    object or as class attribute.
    """
    def render(self, data, accepted_media_type=None, renderer_context=None):
        renderer_context = renderer_context or {}
        request = renderer_context.get('request', None)
        response = renderer_context.get('response', None)
        if not hasattr(self, 'template_name') and not response.template_name:
            raise Exception('the Response object is missing a "template_name"'
                            ' attribute.')
        template_name = response.template_name or self.template_name
        # Here `copy()` is prefered over the creation of a new RequestContext
        # because `render_xml_to_string()` below requires a dictionary.
        context = data.copy()
        context.update(renderer_context)
        return render_xml_to_string(request, template_name, context)
