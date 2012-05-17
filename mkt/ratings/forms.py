from django import forms
from django.forms.models import modelformset_factory

import happyforms
from quieter_formset.formset import BaseModelFormSet
from tower import ugettext_lazy as _lazy

import amo
from amo.utils import raise_required
import reviews

from .models import RatingFlag, Rating


class RatingReplyForm(forms.Form):
    body = forms.CharField(max_length=150,
                           widget=forms.Textarea(attrs={'rows': 2}))

    def clean_body(self):
        body = self.cleaned_data.get('body', '')
        # Whitespace is not a review!
        if not body.strip():
            raise_required()
        return body


class RatingForm(RatingReplyForm):
    score = forms.ChoiceField(choices=([1, _lazy('Thumbs Up')],
                                       [-1, _lazy('Thumbs Down')]))

    def __init__(self, *args, **kw):
        super(RatingForm, self).__init__(*args, **kw)
        # Default to a blank value.
        if self.fields['score'].choices[0][0]:
            self.fields['score'].choices.insert(0, ('', ''))


class RatingFlagForm(forms.ModelForm):

    class Meta:
        model = RatingFlag
        fields = ('flag', 'note', 'rating', 'user')

    def clean(self):
        data = super(RatingFlagForm, self).clean()
        if data.get('note', '').strip():
            data['flag'] = RatingFlag.OTHER
        return data


class BaseRatingFlagFormSet(BaseModelFormSet):

    def __init__(self, *args, **kwargs):
        self.form = ModerateRatingFlagForm
        super(BaseRatingFlagFormSet, self).__init__(*args, **kwargs)

    def save(self):
        for form in self.forms:
            if form.cleaned_data:
                action = int(form.cleaned_data['action'])

                is_flagged = form.instance.reviewflag_set.count() > 0

                if action != reviews.REVIEW_MODERATE_SKIP:  # Delete flags.
                    for flag in form.instance.reviewflag_set.all():
                        flag.delete()

                rating = form.instance
                addon = rating.addon
                if action in (reviews.REVIEW_MODERATE_KEEP,
                              reviews.REVIEW_MODERATE_KEEP):
                    if action == reviews.REVIEW_MODERATE_DELETE:
                        rating_addon, rating_id = rating.addon, rating.id
                        log_action = amo.LOG.DELETE_REVIEW
                        rating.delete()
                    elif action == reviews.REVIEW_MODERATE_KEEP:
                        rating_addon, rating_id = rating.addon, rating
                        rating.update(editorreview=False)
                        log_action = amo.LOG.APPROVE_REVIEW

                    amo.log(log_action, rating_addon, rating_id,
                            details=dict(body=unicode(rating.body),
                                         addon_id=addon.id,
                                         addon_title=unicode(addon.name),
                                         is_flagged=is_flagged))


class ModerateRatingFlagForm(happyforms.ModelForm):

    action_choices = [
        (reviews.REVIEW_MODERATE_KEEP, _lazy('Keep review; remove flags')),
        (reviews.REVIEW_MODERATE_SKIP, _lazy('Skip for now')),
        (reviews.REVIEW_MODERATE_DELETE, _lazy('Delete review'))
    ]
    action = forms.ChoiceField(choices=action_choices, required=False,
                               initial=0, widget=forms.RadioSelect())

    class Meta:
        model = Rating
        fields = ('action',)


RatingFlagFormSet = modelformset_factory(Rating, extra=0,
                                         form=ModerateRatingFlagForm,
                                         formset=BaseRatingFlagFormSet)
