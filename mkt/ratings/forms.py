from django import forms

from reviews.forms import (ReviewForm as OldReviewForm,
                           ReviewReplyForm as OldReviewReplyForm)
from urllib2 import unquote
import re


class ReviewReplyForm(OldReviewReplyForm):
    body = forms.CharField(max_length=150,
                           widget=forms.Textarea(attrs={'rows': 2}))


class ReviewForm(OldReviewForm, ReviewReplyForm):
    flags = re.I | re.L | re.U | re.M
    # This matches the following three types of patterns:
    # http://... or https://..., RFC 3986 compliant host names, and IPv4
    # octets. It does not match IPv6 addresses or long strings such as
    # "example dot com".
    # This is much lighter weight than parsing and recompiling a string
    # then sending it through a DOM tree generator and searching for tokens.
    # Please note that bleach.linkify also currently recognizes only 23
    # potential patterns for TLDs, not the unlimited ICANN set.
    link_pattern = re.compile('((https?://[^\s]+)|(([a-z][0-9a-z\-%]+){1,63}'
            '\.)(([0-9a-z\-%]+){1,63}\.)*([\da-z\-]+){1,63})|((\d{1,3}\.){3}'
            '(\d{1,3}))', flags)

    def _post_clean(self):
        try:
            # unquote the body in case someone tries 'example%2ecom'
            data = unquote(self.cleaned_data['body'])
            if '<br>' in data:
                self.cleaned_data['body'] = re.sub('<br>', "\n", data)
            if self.link_pattern.search(data) is not None:
                self.cleaned_data['flag'] = True
                self.cleaned_data['editorreview'] = True
        except (KeyError, TypeError):
            pass
