from django_jinja import library

from olympia.zadmin.models import get_config as zadmin_get_config


@library.global_function
def get_config(key):
    return zadmin_get_config(key)
