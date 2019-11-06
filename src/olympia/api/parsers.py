from rest_framework.parsers import DataAndFiles, MultiPartParser


class MultiPartParser(MultiPartParser):
    """
    Parser for multipart form data, which may include file data.

    Lifted from https://github.com/tomchristie/django-rest-framework/pull/4026/
    to work around request.data being empty when multipart/form-data is posted.
    See https://github.com/tomchristie/django-rest-framework/issues/3951
    """

    def parse(self, stream, media_type=None, parser_context=None):
        """
        Parses the incoming bytestream as a multipart encoded form,
        and returns a DataAndFiles object.

        `.data` will be a `QueryDict` containing all the form parameters.
        `.files` will be a `QueryDict` containing all the form files.

        For POSTs, accept Django request parsing.  See issue #3951.
        """
        parser_context = parser_context or {}
        request = parser_context['request']
        _request = request._request
        if _request.method == 'POST':
            return DataAndFiles(_request.POST, _request.FILES)
        return super(MultiPartParser, self).parse(
            stream, media_type=media_type, parser_context=parser_context
        )
