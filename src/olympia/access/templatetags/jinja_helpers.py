import jinja2

from django_jinja import library

from .. import acl


@library.global_function
@jinja2.contextfunction
def check_ownership(
    context,
    obj,
    require_owner=False,
    require_author=False,
    ignore_disabled=True,
):
    return acl.check_ownership(
        context['request'],
        obj,
        require_owner=require_owner,
        require_author=require_author,
        ignore_disabled=ignore_disabled,
    )


@library.global_function
@jinja2.contextfunction
def action_allowed(context, permission):
    return acl.action_allowed(context['request'], permission)
