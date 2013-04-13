from django.http import HttpResponse


class HttpPaymentRequired(HttpResponse):
    status_code = 402


class HttpTooManyRequests(HttpResponse):
    status_code = 429


class HttpLegallyUnavailable(HttpResponse):
    """
    451: Unavailable For Legal Reasons
    http://tools.ietf.org/html/draft-tbray-http-legally-restricted-status-00
    """
    status_code = 451
