from tower import ugettext_lazy as _lazy

from editors.forms import ReviewAddonForm, ReviewFileForm
from editors.helpers import ReviewFiles

from mkt.reviewers.utils import ReviewAddon, ReviewHelper


class ReviewAppForm(ReviewAddonForm):

    def __init__(self, *args, **kw):
        super(ReviewAppForm, self).__init__(*args, **kw)
        # We don't want to disable any app files:
        self.addon_files_disabled = tuple([])
        self.fields['notify'].label = _lazy(
            u'Notify me the next time the manifest is updated. (Subsequent '
             'updates will not generate an email.)')


def get_review_form(data, request=None, addon=None, version=None):
    helper = ReviewHelper(request=request, addon=addon, version=version)
    FormClass = ReviewAddonForm
    FormClass = ReviewAppForm
    form = {ReviewAddon: FormClass,
            ReviewFiles: ReviewFileForm}[helper.handler.__class__]
    return form(data, helper=helper)
