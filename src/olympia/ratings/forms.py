import re

from urllib2 import unquote

from django import forms
from django.utils.translation import ugettext, ugettext_lazy as _

from bleach import TLDS

from olympia.amo.utils import raise_required

from .models import RatingFlag


class RatingReplyForm(forms.Form):
    form_id = 'review-reply-edit'

    body = forms.CharField(
        widget=forms.Textarea(
            attrs={'rows': 3, 'id': 'id_review_reply_body', },
        ),
        label='Review',
    )

    def clean_body(self):
        body = self.cleaned_data.get('body', '')
        # Whitespace is not a review!
        if not body.strip():
            raise_required()
        return body


class RatingForm(RatingReplyForm):
    form_id = 'review-edit'

    body = forms.CharField(
        widget=forms.Textarea(
            attrs={'rows': 3, 'id': 'id_review_body', },
        ),
        label='Review',
    )
    rating = forms.ChoiceField(
        zip(range(1, 6), range(1, 6)), label=_(u'Rating')
    )
    flags = re.I | re.L | re.U | re.M
    # This matches the following three types of patterns:
    # http://... or https://..., generic domain names, and IPv4
    # octets. It does not match IPv6 addresses or long strings such as
    # "example dot com".
    link_pattern = re.compile(
        '((://)|'  # Protocols (e.g.: http://)
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


class RatingFlagForm(forms.ModelForm):

    class Meta:
        model = RatingFlag
        fields = ('flag', 'note', 'rating', 'user')

    def clean(self):
        data = super(RatingFlagForm, self).clean()
        if 'note' in data and data['note'].strip():
            data['flag'] = RatingFlag.OTHER
        elif data.get('flag') == RatingFlag.OTHER:
            self.add_error(
                'note',
                ugettext(u'A short explanation must be provided when '
                         u'selecting "Other" as a flag reason.'))
        return data
