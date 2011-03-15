from django import forms
from django.forms.models import modelformset_factory, BaseModelFormSet

import happyforms
from tower import ugettext_lazy as _lazy

import amo
import reviews
from .models import ReviewFlag, Review


class ReviewReplyForm(forms.Form):
    title = forms.CharField(required=False)
    body = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}))


class ReviewForm(ReviewReplyForm):
    rating = forms.ChoiceField(zip(range(1, 6), range(1, 6)))


class ReviewFlagForm(forms.ModelForm):

    class Meta:
        model = ReviewFlag

    def clean(self):
        data = super(ReviewFlagForm, self).clean()
        if 'note' in data and data['note'].strip():
            data['flag'] = ReviewFlag.OTHER
        return data


class BaseReviewFlagFormSet(BaseModelFormSet):

    def __init__(self, *args, **kwargs):
        self.form = ModerateReviewFlagForm
        super(BaseReviewFlagFormSet, self).__init__(*args, **kwargs)

    def save(self):
        for form in self.forms:
            if form.cleaned_data:
                action = int(form.cleaned_data['action'])

                if action != reviews.REVIEW_MODERATE_SKIP:  # Delete flags.
                    for flag in form.instance.reviewflag_set.all():
                        flag.delete()

                review = form.instance
                if action == reviews.REVIEW_MODERATE_DELETE:
                    review_addon = review.addon
                    review_id = review.id
                    review.delete()
                    amo.log(amo.LOG.DELETE_REVIEW, review_addon, review_id,
                            details=dict(title=unicode(review.title),
                                         body=unicode(review.body)))
                elif action == reviews.REVIEW_MODERATE_KEEP:
                    review.editorreview = False
                    review.save()
                    amo.log(amo.LOG.APPROVE_REVIEW, review.addon, review)


class ModerateReviewFlagForm(happyforms.ModelForm):

    action_choices = [(reviews.REVIEW_MODERATE_KEEP,
                       _lazy('Keep review; remove flags')),
                      (reviews.REVIEW_MODERATE_SKIP, _lazy('Skip for now')),
                      (reviews.REVIEW_MODERATE_DELETE, _lazy('Delete review'))]
    action = forms.ChoiceField(choices=action_choices, required=False,
                               initial=0, widget=forms.RadioSelect())

    class Meta:
        model = Review
        fields = ('action',)


ReviewFlagFormSet = modelformset_factory(Review, extra=0,
                                         form=ModerateReviewFlagForm,
                                         formset=BaseReviewFlagFormSet)
