import json

from django.http.multipartparser import parse_header

from rest_framework.renderers import JSONRenderer


class SuccinctJSONRenderer(JSONRenderer):
    """
    JSONRenderer subclass that strips spaces from the output.
    """
    def render(self, data, accepted_media_type=None, renderer_context=None):
        renderer_context = renderer_context or {}
        indent = renderer_context.get('indent', None)

        # Pass to the superclass if the Accept header is set with an explicit
        # indent, if an indent level is manually passed, or if you're attempting
        # to render `None`.
        if accepted_media_type:
             base_media_type, params = parse_header(
                accepted_media_type.encode('ascii'))
             indent = params.get('indent', indent)
        if data is None or indent:
            return super(SuccinctJSONRenderer, self).render(data,
                                                            accepted_media_type,
                                                            renderer_context)

        return json.dumps(data, cls=self.encoder_class, indent=indent,
                          ensure_ascii=self.ensure_ascii, separators=(',', ':'))
