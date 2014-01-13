from django.core.exceptions import ValidationError


def validate_rating(value):
    if not isinstance(value, (int, long)) or value > 5 or value < 1:
        raise ValidationError('Rating must be an integer between 1 and 5, '
                              'inclusive')
