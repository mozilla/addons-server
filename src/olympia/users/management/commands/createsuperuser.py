"""
Management utility to create superusers.
"""
from __future__ import unicode_literals

from django.contrib.auth import get_user_model
from django.core import exceptions
from django.core.management.base import BaseCommand
from django.utils.six.moves import input
from django.utils.text import capfirst


class Command(BaseCommand):
    help = 'Used to create a superuser.'
    required_fields = ['username', 'email']

    def __init__(self, *args, **kwargs):
        super(Command, self).__init__(*args, **kwargs)
        self.UserModel = get_user_model()

    def handle(self, *args, **options):
        user_data = {
            field_name: self.get_value(field_name)
            for field_name in self.required_fields
        }
        self.UserModel._default_manager.create_superuser(
            password=None, **user_data)

    def get_value(self, field_name):
        field = self.UserModel._meta.get_field(field_name)
        value = None
        while value is None:
            raw_value = input('{}: '.format(capfirst(field_name)))
            try:
                value = field.clean(raw_value, None)
            except exceptions.ValidationError as e:
                self.stderr.write('Error: {}'.format('; '.join(e.messages)))
                value = None
        return value
