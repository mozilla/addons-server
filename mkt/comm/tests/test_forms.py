from nose.tools import eq_

import amo.tests

from mkt.comm.forms import CreateCommThreadForm
from mkt.constants import comm


class TestCreateCommThreadForm(amo.tests.TestCase):

   def setUp(self):
       self.app = amo.tests.app_factory()

   def _data(self, **kwargs):
       data = {
           'app': self.app.app_slug,
           'version': self.app.current_version.version,
           'note_type': comm.NO_ACTION,
           'body': 'note body'
       }
       data.update(**kwargs)
       return data

   def test_basic(self):
       data = self._data()
       form = CreateCommThreadForm(data)
       assert form.is_valid()
       eq_(form.cleaned_data['app'], self.app)
       eq_(form.cleaned_data['version'], self.app.current_version)

   def test_version_does_not_exist(self):
       data = self._data(version='1234.9')
       form = CreateCommThreadForm(data)
       assert not form.is_valid()
