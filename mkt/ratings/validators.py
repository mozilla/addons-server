from django.core.exceptions import ValidationError


def validate_rating(value):
    if value > 5 or value < 1 or not isinstance(value, (int, long)):
        raise ValidationError('Rating must be an integer between 1 and 5, '
                              'inclusive')
