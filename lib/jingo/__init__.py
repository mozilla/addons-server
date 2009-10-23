"""Adapter for using Jinja2 with Django."""

from django import http
from django.conf import settings
from django.template.context import get_standard_processors

import jinja2


# We'll put the Environment singleton here.
env = None


def get_env():
    """Configure and return a jinja2 Environment."""
    x = ((jinja2.FileSystemLoader, settings.TEMPLATE_DIRS),
         (jinja2.PackageLoader, settings.INSTALLED_APPS))
    loaders = [loader(p) for loader, places in x for p in places]
    opts = {'trim_blocks': True,
            'extensions': ['jinja2.ext.i18n'],
            'autoescape': True,
            'auto_reload': settings.DEBUG,
            'loader': jinja2.ChoiceLoader(loaders),
            }
    opts.update(getattr(settings, 'JINJA_CONFIG', {}))
    e = jinja2.Environment(**opts)
    e.install_null_translations()
    return e


def render(request, template, context=None, **kwargs):
    """Shortcut like Django's render_to_response, but better."""
    if context is None:
        context = {}
    for processor in get_standard_processors():
        context.update(processor(request))
    rendered = env.get_template(template).render(**context)
    return http.HttpResponse(rendered, **kwargs)


def load_template_tags():
    for app in settings.INSTALLED_APPS:
        try:
            __import__('%s.templatetags' % app)
        except ImportError:
            pass


class Register(object):
    """Decorators to add filters and functions to the template Environment."""

    def __init__(self, env):
        self.env = env

    def filter(self, f):
        self.env.filters[f.__name__] = f
        return f

    def function(self, f):
        self.env.globals[f.__name__] = f
        return f


env = get_env()
register = Register(env)

# Import down here after the env is initialized.
from . import templatetags
load_template_tags()
