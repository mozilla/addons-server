from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse

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


admin.site.register(models.Config)
admin.site.disable_action('delete_selected')
