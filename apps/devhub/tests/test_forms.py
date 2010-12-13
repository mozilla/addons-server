import test_utils

from devhub.forms import NewAddonForm
from files.models import FileUpload


class TestNewAddonForm(test_utils.TestCase):

    def test_only_valid_uploads(self):
        f = FileUpload.objects.create(valid=False)
        form = NewAddonForm({'upload': f.pk})
        assert 'upload' in form.errors

        f.validation = '{"errors": 0}'
        f.save()
        form = NewAddonForm({'upload': f.pk})
        assert 'upload' not in form.errors
