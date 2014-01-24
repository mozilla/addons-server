import json

from django.http.multipartparser import parse_header

from rest_framework.negotiation import DefaultContentNegotiation
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


class FirstAvailableRenderer(DefaultContentNegotiation):
    """
    Content Negotiation class that ignores the Accept header when there is only
    one renderer set on the view. Since most of our views only use the default
    renderer list, which contains only SuccinctJSONRenderer, this means we
    don't have to parse the Accept header for those.

    Override content_negotiation_class in your class if you need something
    different.
    """
    def select_renderer(self, request, renderers, format_suffix=None):
        if len(renderers) == 1:
            return renderers[0], renderers[0].media_type
        else:
            return super(FirstAvailableRenderer, self).select_renderer(
                request, renderers, format_suffix=format_suffix)
