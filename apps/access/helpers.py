import jinja2
from jingo import register

import acl


@register.function
@jinja2.contextfunction
def check_ownership(context, object, require_owner=False):
    return acl.check_ownership(context['request'], object,
                               require_owner=require_owner)
