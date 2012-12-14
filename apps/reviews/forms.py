import re
from urllib2 import unquote

from django import forms
from django.forms.models import modelformset_factory

import happyforms
from tower import ugettext_lazy as _lazy

from bleach import TLDS
from quieter_formset.formset import BaseModelFormSet

import amo
import reviews
from .models import Review, ReviewFlag
from amo.utils import raise_required
from editors.models import ReviewerScore


class ReviewReplyForm(forms.Form):
    title = forms.CharField(required=False)
    body = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}))

    def clean_body(self):
        body = self.cleaned_data.get('body', '')
        # Whitespace is not a review!
        if not body.strip():
            raise_required()
        return body


class ReviewForm(ReviewReplyForm):
    rating = forms.ChoiceField(zip(range(1, 6), range(1, 6)))
    flags = re.I | re.L | re.U | re.M
    # This matches the following three types of patterns:
    # http://... or https://..., generic domain names, and IPv4
    # octets. It does not match IPv6 addresses or long strings such as
    # "example dot com".
    link_pattern = re.compile('((://)|'  # Protocols (e.g.: http://)
                              '((\d{1,3}\.){3}(\d{1,3}))|'
                              '([0-9a-z\-%%]+\.(%s)))' % '|'.join(TLDS),
                              flags)

    def _post_clean(self):
        # Unquote the body in case someone tries 'example%2ecom'.
        data = unquote(self.cleaned_data.get('body', ''))
        if '<br>' in data:
            self.cleaned_data['body'] = re.sub('<br>', '\n', data)
        if self.link_pattern.search(data) is not None:
            self.cleaned_data['flag'] = True
            self.cleaned_data['editorreview'] = True


class ReviewFlagForm(forms.ModelForm):

    class Meta:
        model = ReviewFlag
        fields = ('flag', 'note', 'review', 'user')

    def clean(self):
        data = super(ReviewFlagForm, self).clean()
        if 'note' in data and data['note'].strip():
            data['flag'] = ReviewFlag.OTHER
        return data


class BaseReviewFlagFormSet(BaseModelFormSet):

    def __init__(self, *args, **kwargs):
        self.form = ModerateReviewFlagForm
        self.request = kwargs.pop('request', None)
        super(BaseReviewFlagFormSet, self).__init__(*args, **kwargs)

    def save(self):
        from reviews.helpers import user_can_delete_review

        for form in self.forms:
            if form.cleaned_data and user_can_delete_review(self.request,
                                                            form.instance):
                action = int(form.cleaned_data['action'])

                is_flagged = (form.instance.reviewflag_set.count() > 0)

                if action != reviews.REVIEW_MODERATE_SKIP:  # Delete flags.
                    for flag in form.instance.reviewflag_set.all():
                        flag.delete()

                review = form.instance
                addon = review.addon
                if action == reviews.REVIEW_MODERATE_DELETE:
                    review_addon = review.addon
                    review_id = review.id
                    review.delete()
                    amo.log(amo.LOG.DELETE_REVIEW, review_addon, review_id,
                            details=dict(title=unicode(review.title),
                                         body=unicode(review.body),
                                         addon_id=addon.id,
                                         addon_title=unicode(addon.name),
                                         is_flagged=is_flagged))
                    if self.request:
                        ReviewerScore.award_moderation_points(
                            self.request.amo_user, addon, review_id)
                elif action == reviews.REVIEW_MODERATE_KEEP:
                    review.editorreview = False
                    review.save()
                    amo.log(amo.LOG.APPROVE_REVIEW, review.addon, review,
                            details=dict(title=unicode(review.title),
                                         body=unicode(review.body),
                                         addon_id=addon.id,
                                         addon_title=unicode(addon.name),
                                         is_flagged=is_flagged))
                    if self.request:
                        ReviewerScore.award_moderation_points(
                            self.request.amo_user, addon, review.id)


class ModerateReviewFlagForm(happyforms.ModelForm):

    action_choices = [(reviews.REVIEW_MODERATE_KEEP,
                       _lazy(u'Keep review; remove flags')),
                      (reviews.REVIEW_MODERATE_SKIP, _lazy(u'Skip for now')),
                      (reviews.REVIEW_MODERATE_DELETE,
                       _lazy(u'Delete review'))]
    action = forms.ChoiceField(choices=action_choices, required=False,
                               initial=0, widget=forms.RadioSelect())

    class Meta:
        model = Review
        fields = ('action',)


ReviewFlagFormSet = modelformset_factory(Review, extra=0,
                                         form=ModerateReviewFlagForm,
                                         formset=BaseReviewFlagFormSet)
