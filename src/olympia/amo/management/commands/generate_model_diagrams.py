import shutil
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management import BaseCommand, call_command
from django.db import connection
from django.template.loader import render_to_string


class Command(BaseCommand):
    """
    A Django management command to generate model diagrams and documentation.
    This command performs the following tasks:
    - Cleans existing model documentation.
    - Generates diagrams for models in the specified apps.
    - Creates Markdown documentation for each model, including fields and constraints.
    - Generates an index file for the model documentation.
    Usage:
        Run this command using `python manage.py generate_model_diagrams`.
    """

    help = 'Generate model diagrams'
    model_doc_template = 'model_doc.html'
    model_doc_index_template = 'model_doc_index.html'

    @property
    def root_path(self):
        return Path(settings.ROOT)

    @property
    def docs_path(self):
        return self.root_path / 'docs'

    @property
    def model_doc_path(self):
        return self.docs_path / 'topics' / 'models'

    def graph_model(self, app, name, ext='.png'):
        dot_file = self.model_doc_path / name / ('graph' + ext)
        dot_file.parent.mkdir(parents=True, exist_ok=True)

        call_command('graph_models', app, outputfile=dot_file)

    def create_index(self, name: str, path: Path, model_list: list[str]):
        index_path = path / 'index.md'
        index_path.write_text(
            render_to_string(
                self.model_doc_index_template,
                {
                    'name': name,
                    'models': model_list,
                },
            )
        )

    def clean_model_docs(self):
        self.stdout.write(f'Emptying {self.model_doc_path}')
        if self.model_doc_path.exists():
            shutil.rmtree(self.model_doc_path)
        self.model_doc_path.mkdir(parents=True)

    def model_doc(self, app_name, model):
        model_name = model.__name__
        fields = [
            {
                'name': field.name,
                'type': field.db_type(connection),
                'null': field.null,
                'blank': field.blank,
            }
            for field in model._meta.fields
        ]
        with connection.schema_editor() as schema_editor:
            constraints = [
                {'name': c.name, 'sql': c.constraint_sql(model, schema_editor)}
                for c in model._meta.constraints
            ]
        context = {
            'name': model_name,
            'db_table': model._meta.db_table,
            'description': model.__doc__,
            'fields': fields,
            'constraints': constraints,
        }
        rendered = render_to_string(self.model_doc_template, context)
        doc_path = self.model_doc_path / app_name / (model_name + '.md')
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(rendered)

    def handle(self, *args, **options):
        self.clean_model_docs()

        self.graph_model(name='', app='--all', ext='.dot')
        self.graph_model(name='', app='--all', ext='.png')

        apps_with_models = [
            app
            for app in apps.get_app_configs()
            if app.name.startswith('olympia.')
            and app.models_module
            and len(app.models.items()) > 0
        ]
        app_index = []

        for app in apps_with_models:
            app_name = app.name.split('.')[-1]
            self.stdout.write(f'Generating diagram for {app_name}')
            self.graph_model(name=app_name, app=app_name, ext='.dot')
            self.graph_model(name=app_name, app=app_name, ext='.png')

            app_index.append(f'{app_name}/index')
            app_models = []

            for model in app.get_models():
                self.model_doc(app_name=app_name, model=model)
                index_name = model.__name__
                if index_name not in app_models:
                    app_models.append(index_name)

            self.create_index(
                name=app_name,
                path=(self.model_doc_path / app_name),
                model_list=app_models,
            )

        self.create_index(name='Models', path=self.model_doc_path, model_list=app_index)
