from tower import ugettext_lazy as _lazy

import amo
from editors.forms import ReviewAddonForm, ReviewLogForm

from mkt.reviewers.utils import ReviewHelper


class ReviewAppForm(ReviewAddonForm):

    def __init__(self, *args, **kw):
        kw.update(type=amo.CANNED_RESPONSE_APP)
        super(ReviewAppForm, self).__init__(*args, **kw)
        # We don't want to disable any app files:
        self.addon_files_disabled = tuple([])
        self.fields['notify'].label = _lazy(
            u'Notify me the next time the manifest is updated. (Subsequent '
             'updates will not generate an email.)')


def get_review_form(data, request=None, addon=None, version=None):
    helper = ReviewHelper(request=request, addon=addon, version=version)
    return ReviewAppForm(data, helper=helper)


class ReviewAppLogForm(ReviewLogForm):

    def __init__(self, *args, **kwargs):
        super(ReviewAppLogForm, self).__init__(*args, **kwargs)
        self.fields['search'].widget.attrs = {
            # L10n: Descript of what can be searched for.
            'placeholder': _lazy(u'app, reviewer, or comment'),
            'size': 30}
