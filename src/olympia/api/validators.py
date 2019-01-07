import unicodedata

from django.utils.translation import ugettext

from rest_framework import serializers


class OneOrMorePrintableCharacterValidator:
    def __init__(self, unicode_categories=None):
        self.unicode_categories = unicode_categories or ('L', 'N', 'P', 'S')

    def __call__(self, string):
        for character in string:
            if unicodedata.category(character)[0] in self.unicode_categories:
                return
        raise serializers.ValidationError(
            ugettext(u'Must contain at least one printable character.'))
