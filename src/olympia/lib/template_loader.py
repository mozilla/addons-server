# -*- coding: utf-8 -*-

from django.conf import settings
from jingo import Loader as JingoLoader, Template


class Loader(JingoLoader):
    """Use JINGO_EXCLUDE_PATHS to exclude templates based on their path.

    jingo.Loader has a JINGO_EXCLUDE_APPS that only allows to provide the "app"
    part of a template (the part before the first "/").

    It doesn't allow avoiding specific templates, for example mail templates
    that we would like Django's template loader to render.

    Using this loader, we may use the JINGO_EXCLUDE_PATHS settings to decide
    whether a template should be rendered by Jingo or not.

    Example usage:

    JINGO_EXCLUDE_PATHS = (
        'foo/bar',
    )

    This will exclude all templates starting with 'foo/bar', but not 'foo/baz'
    nor 'quux/foo/bar'.

    """

    def _valid_template(self, template_name):
        """Don't load templates if their name start with a prefix from
        JINGO_EXCLUDE_PATHS."""
        if isinstance(template_name, Template):  # It's already a Template.
            return True

        jingo_valid = super(Loader, self)._valid_template(template_name)
        if not jingo_valid:
            return False

        for path_prefix in getattr(settings, 'JINGO_EXCLUDE_PATHS', []):
            if path_prefix in template_name:
                return False

        return True
