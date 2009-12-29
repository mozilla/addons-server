from django.conf import settings


class Prefixer(object):

    def __init__(self, request):
        self.request_path = request.path

        self.locale, self.app, self.shortened_path = self.split_request()

    def split_request(self):
        """
        Split the requested path into (locale, app, remainder).

        locale and app will be empty strings if they're not found.
        """
        path = self.request_path.lstrip('/')

        # Use partition instead of split since it always returns 3 parts.
        first, _, first_rest = path.partition('/')
        second, _, rest = first_rest.partition('/')

        if first in settings.LANGUAGES:
            if second in settings.SUPPORTED_APPS:
                return first, second, rest
            else:
                return first, '', first_rest
        elif first in settings.SUPPORTED_APPS:
            return '', first, first_rest
        else:
            if second in settings.SUPPORTED_APPS:
                return '', second, rest
            else:
                return '', '', path

    def fix(self, path):
        path = path.lstrip('/')
        url_parts = []

        locale = self.locale if self.locale else settings.LANGUAGE_CODE
        url_parts.append(locale)

        if path.partition('/')[0] not in settings.SUPPORTED_NONAPPS:
            app = self.app if self.app else settings.DEFAULT_APP
            url_parts.append(app)

        url_parts.append(path)

        return '/' + '/'.join(url_parts)
