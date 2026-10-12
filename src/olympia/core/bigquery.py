from django.conf import settings

from google.cloud import bigquery


def create_client():
    return bigquery.Client.from_service_account_json(
        settings.GOOGLE_APPLICATION_CREDENTIALS_BIGQUERY
    )
