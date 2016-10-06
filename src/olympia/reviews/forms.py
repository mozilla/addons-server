import re
from urllib2 import unquote

from django import forms
from django.forms.models import modelformset_factory
from django.utils.translation import ugettext as _, ugettext_lazy as _lazy

from bleach import TLDS
from quieter_formset.formset import BaseModelFormSet

from olympia import reviews
from olympia.amo.utils import raise_required
from olympia.lib import happyforms

from .models import Review, ReviewFlag


class ReviewReplyForm(forms.Form):
    form_id = "review-reply-edit"

    title = forms.CharField(
        required=False,
        label=_lazy(u"Title"),
        widget=forms.TextInput(
            attrs={'id': 'id_review_reply_title', },
        ),
    )
    body = forms.CharField(
        widget=forms.Textarea(
            attrs={'rows': 3, 'id': 'id_review_reply_body', },
        ),
        label="Review",
    )

    def clean_body(self):
        body = self.cleaned_data.get('body', '')
        # Whitespace is not a review!
        if not body.strip():
            raise_required()
        return body


class ReviewForm(ReviewReplyForm):
    form_id = "review-edit"

    title = forms.CharField(
        required=False,
        label=_lazy(u"Title"),
        widget=forms.TextInput(
            attrs={'id': 'id_review_title', },
        ),
    )
    body = forms.CharField(
        widget=forms.Textarea(
            attrs={'rows': 3, 'id': 'id_review_body', },
        ),
        label="Review",
    )
    rating = forms.ChoiceField(
        zip(range(1, 6), range(1, 6)), label=_lazy(u"Rating")
    )
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
        elif data.get('flag') == ReviewFlag.OTHER:
            self.add_error(
                'note',
                _(u'A short explanation must be provided when selecting '
                  u'"Other" as a flag reason.'))
        return data


class BaseReviewFlagFormSet(BaseModelFormSet):

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(BaseReviewFlagFormSet, self).__init__(*args, **kwargs)

    def save(self):
        from olympia.reviews.helpers import user_can_delete_review

        for form in self.forms:
            if form.cleaned_data and user_can_delete_review(self.request,
                                                            form.instance):
                action = int(form.cleaned_data['action'])

                if action == reviews.REVIEW_MODERATE_DELETE:
                    form.instance.moderator_delete(user=self.request.user)
                elif action == reviews.REVIEW_MODERATE_KEEP:
                    form.instance.moderator_approve(user=self.request.user)


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
