import jinja2

from django_jinja import library

from .. import acl


@library.global_function
@jinja2.pass_context
def action_allowed(context, permission):
    return acl.action_allowed(context['request'], permission)
