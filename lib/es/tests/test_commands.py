import os
import subprocess
import sys
import time

from nose.tools import eq_

from django.conf import settings
from django.db import connection

import amo.search
import amo.tests
from addons.models import AddonCategory, Category
from amo.urlresolvers import reverse
from amo.utils import urlparams
from es.management.commands.reindex import (call_es, unflag_database,
                                            database_flagged)
from mkt.webapps.models import Webapp


class TestIndexCommand(amo.tests.ESTestCase):
    fixtures = ['webapps/337141-steamcube']

    def setUp(self):
        super(TestIndexCommand, self).setUp()
        if database_flagged():
            unflag_database()

        self.url = reverse('search.search')
        self.webapp = Webapp.objects.get(id=337141)
        self.apps = [self.webapp]
        self.cat = Category.objects.create(name='Games', type=amo.ADDON_WEBAPP)
        AddonCategory.objects.create(addon=self.webapp, category=self.cat)
        # Emit post-save signal so the app gets reindexed.
        self.webapp.save()
        self.refresh()

        # XXX I have not find a better way for now
        source = os.path.join(os.path.dirname(__file__), 'settings.tmpl')
        self.settings = 'settings_%s' % os.urandom(5).encode('hex')
        self.target = os.path.join(settings.ROOT, self.settings + '.py')
        self.target_pyc = self.target + 'c'
        with open(source) as f:
            data = {'DB': settings.DATABASES['default']['NAME']}
            with open(self.target, 'w') as target:
                target.write(f.read() % data)

        # any index created during the test will be deleted
        self.indices = call_es('_status').json()['indices'].keys()

    def tearDown(self):
        for file_ in (self.target, self.target_pyc):
            if os.path.exists(file_):
                os.remove(file_)

        current_indices = call_es('_status').json()['indices'].keys()
        for index in current_indices:
            if index not in self.indices:
                call_es(index, method='DELETE')

    def check_results(self, params, expected, sorted=True):
        r = self.client.get(urlparams(self.url, **params), follow=True)
        eq_(r.status_code, 200, str(r.content))
        got = self.get_results(r)
        if sorted:
            got.sort()
            expected.sort()

        eq_(got, expected,
            'Got: %s. Expected: %s. Parameters: %s' % (got, expected, params))
        return r

    def get_results(self, r, sort=False):
        """Return pks of add-ons shown on search results page."""
        pager = r.context['pager']
        results = []
        for page_num in range(pager.paginator.num_pages):
            results.extend([item.pk for item
                            in pager.paginator.page(page_num + 1)])
        if sort:
            results = sorted(results)
        return results

    def _create_app(self, name='app', signal=True):
        webapp = Webapp.objects.create(status=amo.STATUS_PUBLIC,
                                       name=name,
                                       type=amo.ADDON_WEBAPP)
        AddonCategory.objects.create(addon=webapp, category=self.cat)
        webapp.save(_signal=signal)
        return webapp

    def test_reindexation(self):
        # adding a web app
        webapp2 = self._create_app('neat app 2')
        self.refresh()

        # this search should return both apps
        r = self.check_results({'sort': 'popularity'},
                               [webapp2.pk, self.webapp.pk])

        # adding 5 more apps
        webapps = [self._create_app('moarneatapp %d' % i)
                   for i in range(5)]
        self.refresh()

        # XXX is there a cleaner way ?
        # all I want is to have those webapp in the DB
        # so the reindex command sees them
        connection._commit()
        connection.clean_savepoints()

        # right now, the DB should be composed of
        # two indexes, and two aliases, let's check
        # we have two aliases
        aliases = call_es('_aliases').json()
        old_aliases = [(index, aliases['aliases'].keys()[0])
                       for index, aliases in aliases.items()
                       if len(aliases['aliases']) > 0 and
                       index.startswith('test')]
        old_aliases.sort()

        # now doing a reindexation in a background process
        args = [sys.executable, 'manage.py', 'reindex', '--prefix=test_',
                '--settings=%s' % self.settings]

        indexer = subprocess.Popen(args,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   cwd=settings.ROOT)

        try:
            # we should be able to continue some searching in the foreground
            # and always get our documents
            #
            # we should also be able to index new documents, and
            # they should not be lost
            count = 1
            wanted = [app.pk for app in webapps] + [webapp2.pk, self.webapp.pk]

            # let's add more apps, and also do some searches
            while indexer.poll() is None and count < 8:
                r = self.client.get(urlparams(self.url, sort='popularity'),
                                    follow=True)
                eq_(r.status_code, 200, str(r.content))
                got = self.get_results(r)
                got.sort()
                self.assertEqual(len(got), len(wanted), (got, wanted))
                wanted.append(self._create_app('moar %d' % count).pk)
                self.refresh()
                connection._commit()
                connection.clean_savepoints()
                count += 1
                time.sleep(.1)

            if count < 3:
                raise AssertionError("Could not index enough objects for the "
                                     "test to be meaningful.")
        except Exception:
            indexer.terminate()
            raise

        stdout, stderr = indexer.communicate()
        self.assertTrue('Reindexation done' in stdout, stdout + '\n' + stderr)

        amo.search.get_es().refresh()
        # the reindexation is done, let's double check we have all our docs
        self.check_results({'sort': 'popularity'}, wanted)

        # let's check the aliases as well, we should have 2
        aliases = call_es('_aliases').json()
        new_aliases = [(index, aliases['aliases'].keys()[0])
                       for index, aliases in aliases.items()
                       if len(aliases['aliases']) > 0 and
                       index.startswith('test')]
        new_aliases.sort()
        self.assertTrue(len(new_aliases), 2)

        # and they should be new aliases
        self.assertNotEqual(new_aliases, old_aliases)

    def test_remove_index(self):
        # Putting a test_amo index in the way.
        es = amo.search.get_es()

        for index in es.get_indices().keys():
            for prefix in ('test_amo', 'test_amo_stats'):
                if index.startswith(prefix + '-'):
                    es.delete_alias(prefix, [index])
                    es.delete_index(index)
                    es.create_index(prefix)

        # reindexing the first app
        self.webapp.save()
        self.refresh()

        # now doing a reindexation in a background process
        args = [sys.executable, 'manage.py', 'reindex', '--prefix=test_',
                '--settings=%s' % self.settings]

        indexer = subprocess.Popen(args,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   cwd=settings.ROOT)
        stdout, stderr = indexer.communicate()
        self.assertTrue('Reindexation done' in stdout, stdout + '\n' + stderr)
