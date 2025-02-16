#!/usr/bin/env python

import os

import django
from django.apps import apps
from django.core.management import call_command


# Set up Django environment
print('Setting up Django environment')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
django.setup()

root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
docs_path = os.path.join(root_path, 'docs')
docs_dot_path = os.path.join(docs_path, 'dot_files')


def graph_model(name=None, ext='.png'):
    app_name = name.split('.')[-1] if name else 'addons-server'
    dot_file = os.path.join(docs_dot_path, app_name + ext)

    call_command('graph_models', app_name if name else '--all', outputfile=dot_file)


if not os.path.exists(docs_dot_path):
    os.makedirs(docs_dot_path)

# empty the directory
print(f'Emptying {docs_dot_path}')
for file in os.listdir(docs_dot_path):
    os.remove(os.path.join(docs_dot_path, file))

print('Generating diagram for addons-server')
graph_model(ext='.dot')
graph_model(ext='.png')

for app in apps.get_app_configs():
    if (
        app.name.startswith('olympia.')
        and app.models_module
        and len(app.models.items()) > 0
    ):
        print('Generating diagram for', app.name)
        graph_model(name=app.name, ext='.dot')
        graph_model(name=app.name, ext='.png')
