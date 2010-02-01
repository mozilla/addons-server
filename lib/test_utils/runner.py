"""
This is a test runner that monkeypatches connection.creation to skip database
creation if it appears that the db already exists.  Your tests will run much
faster.

To force the normal database creation, define the environment variable
"FORCE_DB".  It doesn't really matter what the value is, we just check to see
if it's there.
"""
import os

from django.db import connections
from django.db.backends.creation import TEST_DATABASE_PREFIX
from django.db.backends.mysql import creation as mysql

import django_nose


# XXX: hard-coded to mysql.
class SkipDatabaseCreation(mysql.DatabaseCreation):

    def _create_test_db(self, verbosity, autoclobber):
        ### Oh yes, let's copy from django/db/backends/creation.py
        suffix = self.sql_table_creation_suffix()

        if self.connection.settings_dict['TEST_NAME']:
            test_database_name = self.connection.settings_dict['TEST_NAME']
        else:
            test_database_name = TEST_DATABASE_PREFIX + self.connection.settings_dict['NAME']
        qn = self.connection.ops.quote_name

        # Create the test database and connect to it. We need to autocommit
        # if the database supports it because PostgreSQL doesn't allow
        # CREATE/DROP DATABASE statements within transactions.
        cursor = self.connection.cursor()
        self.set_autocommit()

        ### That's enough copying.

        # If we couldn't create the test db, assume it already exists.
        try:
            cursor.execute("CREATE DATABASE %s %s" %
                           (qn(test_database_name), suffix))
        except Exception, e:
            print '...Skipping setup of %s!' % test_database_name
            print '...Try FORCE_DB=true if you need fresh databases.'
            return test_database_name

        # Drop the db we just created, then do the normal setup.
        cursor.execute("DROP DATABASE %s %s" %
                       (qn(test_database_name), suffix))
        return super(SkipDatabaseCreation, self)._create_test_db(
            verbosity, autoclobber)


class RadicalTestSuiteRunner(django_nose.NoseTestSuiteRunner):

    def setup_databases(self):
        if not os.getenv('FORCE_DB'):
            for alias in connections:
                connection = connections[alias]
                connection.creation.__class__ = SkipDatabaseCreation
        return super(RadicalTestSuiteRunner, self).setup_databases()

    def teardown_databases(self, old_config):
        if os.getenv('FORCE_DB'):
            super(RadicalTestSuiteRunner, self).teardown_databases(old_config)
