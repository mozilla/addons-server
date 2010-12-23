
from django.conf import settings

from devhub.forms import NewAddonForm, ContribForm
from files.models import FileUpload
import test_utils

from nose.tools import eq_


class TestNewAddonForm(test_utils.TestCase):

    def test_only_valid_uploads(self):
        f = FileUpload.objects.create(valid=False)
        form = NewAddonForm({'upload': f.pk})
        assert 'upload' in form.errors

        f.validation = '{"errors": 0}'
        f.save()
        form = NewAddonForm({'upload': f.pk})
        assert 'upload' not in form.errors


class TestContribForm(test_utils.TestCase):

    def test_neg_suggested_amount(self):
        form = ContribForm({'suggested_amount': -10})
        assert not form.is_valid()
        eq_(form.errors['suggested_amount'][0],
            'Please enter a suggested amount greater than 0.')

    def test_max_suggested_amount(self):
        form = ContribForm({'suggested_amount':
                            settings.MAX_CONTRIBUTION + 10})
        assert not form.is_valid()
        eq_(form.errors['suggested_amount'][0],
            'Please enter a suggested amount less than $%s.' %
            settings.MAX_CONTRIBUTION)
