import os
from importlib import import_module


# get the right settings module
settings = import_module(
    os.environ.get('DJANGO_SETTINGS_MODULE', 'settings_local'))
