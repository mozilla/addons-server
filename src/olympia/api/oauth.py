import string
import commonware.log
from oauthlib import oauth1
from oauthlib.common import safe_string_equals

from .models import Access, Nonce, Token, REQUEST_TOKEN, ACCESS_TOKEN

DUMMY_CLIENT_KEY = u'DummyOAuthClientKeyString'
DUMMY_TOKEN = u'DummyOAuthToken'
DUMMY_SECRET = u'DummyOAuthSecret'

log = commonware.log.getLogger('z.api')


class OAuthServer(oauth1.Server):
    safe_characters = set(string.printable)
    nonce_length = (7, 128)
    access_token_length = (8, 128)
    request_token_length = (8, 128)
    verifier_length = (8, 128)
    client_key_length = (8, 128)
    enforce_ssl = False  # SSL enforcement is handled by ops. :-)

    def validate_client_key(self, key):
        self.attempted_key = key
        return Access.objects.filter(key=key).exists()

    def get_client_secret(self, key):
        # This method returns a dummy secret on failure so that auth
        # success and failure take a codepath with the same run time,
        # to prevent timing attacks.
        try:
            # OAuthlib needs unicode objects, django-aesfield returns a string.
            return Access.objects.get(key=key).secret.decode('utf8')
        except Access.DoesNotExist:
            return DUMMY_SECRET

    @property
    def dummy_client(self):
        return DUMMY_CLIENT_KEY

    @property
    def dummy_request_token(self):
        return DUMMY_TOKEN

    @property
    def dummy_access_token(self):
        return DUMMY_TOKEN

    def validate_timestamp_and_nonce(self, client_key, timestamp, nonce,
                                     request_token=None, access_token=None):
        n, created = Nonce.objects.get_or_create(
            key=client_key + nonce,
            token_key=request_token,
            consumer_key=access_token)
        return created

    def validate_requested_realm(self, client_key, realm):
        return True

    def validate_realm(self, client_key, access_token, uri=None,
                       required_realm=None):
        return True

    def validate_redirect_uri(self, client_key, redirect_uri):
        return True

    def validate_request_token(self, client_key, request_token):
        # This method must take the same amount of time/db lookups for
        # success and failure to prevent timing attacks.
        return Token.objects.filter(token_type=REQUEST_TOKEN,
                                    creds__key=client_key,
                                    key=request_token).exists()

    def validate_access_token(self, client_key, access_token):
        # This method must take the same amount of time/db lookups for
        # success and failure to prevent timing attacks.
        return Token.objects.filter(token_type=ACCESS_TOKEN,
                                    creds__key=client_key,
                                    key=access_token).exists()

    def validate_verifier(self, client_key, request_token, verifier):
        # This method must take the same amount of time/db lookups for
        # success and failure to prevent timing attacks.
        try:
            t = Token.objects.get(key=request_token, token_type=REQUEST_TOKEN)
            candidate = t.verifier
        except Token.DoesNotExist:
            candidate = ''
        return safe_string_equals(candidate, verifier)

    def get_request_token_secret(self, client_key, request_token):
        # This method must take the same amount of time/db lookups for
        # success and failure to prevent timing attacks.
        try:
            t = Token.objects.get(key=request_token, creds__key=client_key,
                                  token_type=REQUEST_TOKEN)
            return t.secret
        except Token.DoesNotExist:
            return DUMMY_SECRET

    def get_access_token_secret(self, client_key, request_token):
        # This method must take the same amount of time/db lookups for
        # success and failure to prevent timing attacks.
        try:
            t = Token.objects.get(key=request_token, creds__key=client_key,
                                  token_type=ACCESS_TOKEN)
        except Token.DoesNotExist:
            return DUMMY_SECRET

        return t.secret
