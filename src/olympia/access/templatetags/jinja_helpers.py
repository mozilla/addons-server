from django_jinja import library

from .. import acl


library.global_function(acl.action_allowed_for)
