from django.conf import settings
from django.contrib import admin, auth
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.html import format_html
from django.urls import reverse

from olympia.accounts.utils import redirect_for_login

from . import models


def related_content_link(obj, related_class, related_field,
                         related_manager='objects', count=None):
    """
    Return a link to the admin changelist for the instances of related_class
    linked to the object.
    """
    url = 'admin:{}_{}_changelist'.format(
        related_class._meta.app_label, related_class._meta.model_name)
    queryset = getattr(related_class, related_manager).filter(
        **{related_field: obj})
    if count is None:
        count = queryset.count()
    return format_html(
        '<a href="{}?{}={}">{}</a>',
        reverse(url), related_field, obj.pk, count)


def related_single_content_link(obj, related_field):
    """
    Return a link to the admin change page for a related instance linked to the
    object.
    """
    instance = getattr(obj, related_field)
    if instance:
        related_class = instance._meta.model
        url = 'admin:{}_{}_change'.format(
            related_class._meta.app_label, related_class._meta.model_name)
        return format_html(
            '<a href="{}">{}</a>',
            reverse(url, args=(instance.pk,)), repr(instance))
    else:
        return ''


# Hijack the admin's login to use our pages.
def login(request):
    # if the user has permission, just send them to the index page
    if request.method == 'GET' and admin.site.has_permission(request):
        next_path = request.GET.get(auth.REDIRECT_FIELD_NAME)
        return redirect(next_path or 'admin:index')
    # otherwise, they're logged in but don't have permission return a 403.
    elif request.user.is_authenticated:
        raise PermissionDenied
    else:
        return redirect_for_login(request)


admin.site.register(models.Config)
admin.site.disable_action('delete_selected')
admin.site.site_url = settings.EXTERNAL_SITE_URL
admin.site.site_header = admin.site.index_title = 'AMO Administration'
admin.site.login = login
