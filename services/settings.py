import os

from django.utils import importlib


# get the right settings module
settings = importlib.import_module(
    os.environ.get('DJANGO_SETTINGS_MODULE', 'settings_local'))
