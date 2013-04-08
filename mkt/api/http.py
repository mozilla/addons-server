from django.http import HttpResponse


class HttpPaymentRequired(HttpResponse):
    status_code = 402


class HttpTooManyRequests(HttpResponse):
    status_code = 429
