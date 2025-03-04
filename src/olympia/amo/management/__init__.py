import logging
import os
import shutil

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from celery import chord, group

from olympia.amo.utils import chunked


class ProcessObjectsCommand(BaseCommand):
    """
    A generic command base class to run a task on objects.

    Inherit from it and implement `get_model()` and `get_tasks()`.
    """

    def get_model(self):
        """Return the model that this command manipulates."""
        raise NotImplementedError

    def get_tasks(self):
        """Return a dict with information about tasks the command handles.

        Keys are the aliases that will be used as argument on the command line,
        and the values are dictionaries describing which task to run on what.
        Each dictionary describing the tasks need to provide:
        - task: a reference to the task to delay (generally a function
            decorated with @task)
        - queryset_filters: a list or tuple of Q objects to apply to the
            queryset of objects to determine what to run the task on

        The following optional key-values can be set:
        - distinct: a boolean indicating whether or not the queryset of objects
            to run the task on should have a distinct() added.
        - pre: a method to further pre process the pks of the objects to run
            the task on. Must return the pks
        - kwargs: any extra kwargs you want to apply to delay() when calling
            the task.
        - allowed_kwargs: any extra boolean kwargs that will be passed as
            kwargs to the delay() call from the command line arguments. Make
            sure to add it to `add_arguments` too if it's not there already.
        """
        raise NotImplementedError

    def add_arguments(self, parser):
        """Handle command arguments."""
        model = self.get_model()
        verbose_name_plural = model._meta.verbose_name_plural
        # Note: technically --task is not a task, but rather the name of one of
        # the entries in the dict returned by get_tasks(), which might differ
        # from the name of the task itself.
        parser.add_argument(
            '--task',
            action='store',
            dest='task_info',
            type=str,
            help=f'What task to run on the {verbose_name_plural}.',
        )

        parser.add_argument(
            '--with-deleted',
            action='store_true',
            dest='with_deleted',
            help=f'Include deleted {verbose_name_plural} when determining which '
            f'{verbose_name_plural} to process.',
        )

        parser.add_argument(
            '--ids',
            action='store',
            dest='ids',
            help=f'Only apply task to specific {verbose_name_plural} ids '
            '(comma-separated).',
        )

        parser.add_argument(
            '--limit',
            action='store',
            dest='limit',
            type=int,
            help=f'Only apply task to the first X {verbose_name_plural} ids.',
        )

        parser.add_argument(
            '--batch-size',
            action='store',
            dest='batch_size',
            type=int,
            default=100,
            help=f'Split the {verbose_name_plural} into X size chunks. Default 100.',
        )

    def get_pks(self, manager, q_objects, *, distinct=False):
        qs = manager.filter(*q_objects)
        pks = qs.values_list('pk', flat=True).order_by('pk')
        if distinct:
            pks = pks.distinct()
        return pks

    def get_base_queryset(self, options):
        model = self.get_model()
        if options.get('with_deleted'):
            base_qs = model.unfiltered
        else:
            base_qs = model.objects
        if options.get('ids'):
            ids_list = options.get('ids').split(',')
            base_qs = base_qs.filter(id__in=ids_list)
        return base_qs

    def handle(self, *args, **options):
        tasks = self.get_tasks()
        task_info = tasks.get(options.get('task_info'))
        if not task_info:
            raise CommandError(
                'Unknown task provided. Options are: %s' % ', '.join(tasks.keys())
            )
        base_qs = self.get_base_queryset(options)
        pks = self.get_pks(
            base_qs,
            task_info['queryset_filters'],
            distinct=task_info.get('distinct'),
        )
        if options.get('limit'):
            pks = pks[: options.get('limit')]
        if 'pre' in task_info:
            # This is run in process to ensure its run before the tasks.
            pks = task_info['pre'](pks)
        if pks:
            kwargs = task_info.get('kwargs', {})
            if task_info.get('allowed_kwargs'):
                kwargs.update(
                    {arg: options.get(arg, None) for arg in task_info['allowed_kwargs']}
                )
            # All the remaining tasks go in one group.
            grouping = []
            for chunk in chunked(pks, options.get('batch_size')):
                grouping.append(task_info['task'].subtask(args=[chunk], kwargs=kwargs))

            # Add the post task on to the end.
            post = None
            if 'post' in task_info:
                post = task_info['post'].subtask(args=[], kwargs=kwargs, immutable=True)
                ts = chord(grouping, post)
            else:
                ts = group(grouping)
            ts.apply_async()


storage_structure = {
    'files': '',
    'shared_storage': {
        'tmp': {
            'addons': '',
            'data': '',
            'file_viewer': '',
            'guarded-addons': '',
            'icon': '',
            'log': '',
            'persona_header': '',
            'preview': '',
            'test': '',
            'uploads': '',
        },
        'uploads': {
            'addon_icons': '',
            'previews': '',
            'userpics': '',
        },
    },
}


class BaseDataCommand(BaseCommand):
    # Settings for django-dbbackup
    data_backup_dirname = os.path.abspath(os.path.join(settings.ROOT, 'backups'))
    data_backup_init = '_init'
    data_backup_db_filename = 'db.sql'
    data_backup_storage_filename = 'storage.tar'

    logger = logging

    def backup_dir_path(self, name):
        return os.path.abspath(os.path.join(self.data_backup_dirname, name))

    def backup_db_path(self, name):
        return os.path.abspath(
            os.path.join(self.backup_dir_path(name), self.data_backup_db_filename)
        )

    def backup_storage_path(self, name):
        return os.path.abspath(
            os.path.join(self.backup_dir_path(name), self.data_backup_storage_filename)
        )

    def clean_dir(self, name: str) -> None:
        path = self.backup_dir_path(name)
        logging.info(f'Clearing {path}')
        shutil.rmtree(path, ignore_errors=True)

    def make_dir(self, name: str, force: bool = False) -> None:
        path = self.backup_dir_path(name)
        path_exists = os.path.exists(path)

        if path_exists:
            if force:
                self.clean_dir(name)
            else:
                raise CommandError(
                    f'path {path} already exists.' 'Use --force to overwrite.'
                )

        os.makedirs(path, exist_ok=True)

    def _clean_storage(
        self, root: str, dir_dict: dict[str, str | dict], clean: bool = False
    ) -> None:
        for key, value in dir_dict.items():
            curr_path = os.path.join(root, key)
            if isinstance(value, dict):
                self._clean_storage(curr_path, value, clean=clean)
            else:
                if clean:
                    shutil.rmtree(curr_path, ignore_errors=True)
                os.makedirs(curr_path, exist_ok=True)

    def make_storage(self, clean: bool = False):
        self.logger.info('Making storage...')
        self._clean_storage(settings.STORAGE_ROOT, storage_structure, clean=clean)
