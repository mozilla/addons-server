from editors.forms import ReviewAddonForm

# TODO: Remove
from editors.helpers import ReviewFiles
from editors.forms import ReviewFileForm

from mkt.reviewers.utils import ReviewAddon, ReviewHelper


class ReviewAppForm(ReviewAddonForm):

    def __init__(self, *args, **kw):
        super(ReviewAppForm, self).__init__(*args, **kw)
        # We don't want to disable any app files:
        self.addon_files_disabled = tuple([])


def get_review_form(data, request=None, addon=None, version=None):
    helper = ReviewHelper(request=request, addon=addon, version=version)
    FormClass = ReviewAddonForm
    FormClass = ReviewAppForm
    form = {ReviewAddon: FormClass,
            ReviewFiles: ReviewFileForm}[helper.handler.__class__]
    return form(data, helper=helper)
