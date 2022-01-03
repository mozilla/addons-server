from django_jinja import library
import jinja2

from olympia.accounts.utils import path_with_query
from olympia.amo.templatetags.jinja_helpers import drf_url


@library.global_function
@jinja2.pass_context
def login_link(context):
    next_path = path_with_query(context['request'])
    login_start = drf_url(context, 'accounts.login_start')
    return f'{login_start}?to={next_path}'


@library.global_function
@jinja2.pass_context
def register_link(context):
    return login_link(context)
