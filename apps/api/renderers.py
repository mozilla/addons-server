import json

from rest_framework.renderers import (JSONRenderer as BaseJSONRenderer,
                                      XMLRenderer)

from amo.utils import JSONEncoder

from .views import render_xml_to_string


class JSONRenderer(BaseJSONRenderer):

    encoder_class = JSONEncoder

    def render(self, data, *args, **kwargs):
        """
        Serialize with JSONEncoder and reload the json to generate
        a valid dict.
        """
        data = json.loads(json.dumps(data, cls=self.encoder_class))
        return super(JSONRenderer, self).render(data, *args, **kwargs)


class XMLTemplateRenderer(XMLRenderer):
    """
    Renders an XML template. Supports `template_name` kwargs from `Response`
    object or as class attribute.
    """

    def render(self, data, accepted_media_type=None, renderer_context=None):
        request = renderer_context['request']
        response = renderer_context['response']
        if not hasattr(self, 'template_name') and not response.template_name:
            raise Exception('the Response object is missing a "template_name"'
                            ' attribute.')
        template_name = response.template_name or self.template_name
        return render_xml_to_string(request, template_name, data)
