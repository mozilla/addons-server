import browserid
import browserid.certificates
import browserid.jwt
from browserid.verifiers import local
from browserid.utils import unbundle_certs_and_assertion
from browserid.utils import decode_bytes, encode_bytes
from browserid.utils import decode_json_bytes, encode_json_bytes
from browserid.errors import (ConnectionError, InvalidIssuerError,
                              InvalidSignatureError, ExpiredSignatureError)

import requests
from requests.exceptions import RequestException

from binascii import hexlify
import time
import json

def fetch_public_key(url, *args):
    """Fetch the public key from the given URL."""
    # Try to find the public key.  If it can't be found then we
    # raise an InvalidIssuerError.  Any other connection-related
    # errors are passed back up to the caller.
    response = _get(url)
    if response.status_code == 200:
        try:
            try:
                key = parse_jwt(response.text).payload['jwk'][0]
            except ValueError:
                key = json.loads(response.text)['jwk'][0]
        except (ValueError, KeyError):
            raise InvalidIssuerError('Host %r has malformed public key '
                                     'document' % url)
    else:
        raise InvalidIssuerError('Can not retrieve key from "%s"' % url)

    return key


def _get(url):
    """Fetch resource with requests."""
    try:
        return requests.get(url)
    except RequestException, e:
        msg = "Impossible to get %s. Reason: %s" % (url, str(e))
        raise ConnectionError(msg)


def parse_jwt(data):
    """Parse a JWT from a string."""
    header, payload, signature = data.split(".")
    signed_data = header + "." + payload
    try:
        header = decode_json_bytes(header)
    except KeyError:
        raise ValueError("badly formed JWT header")
    payload = decode_json_bytes(payload)
    signature = decode_bytes(signature)
    return ReceiptJWT(header, payload, signature, signed_data)


def jwt_cert_to_key(jwtoken):
    """Converts a JWT encapsulated JWK key into something usable by PyBrowserID.jwt"""
    if type(jwtoken) != dict:
        jwtoken = parse_jwt(jwtoken)
    return jwk_to_key(jwtoken.payload['jwk'][0], jwtoken.header['alg'])


def jwk_to_key(jwk, alg):
    """Quick'n'simple format conversion"""
    jwk['e'] = long(hexlify(browserid.jwt.decode_bytes(jwk['exp'])), 16)
    jwk['n'] = long(hexlify(browserid.jwt.decode_bytes(jwk['mod'])), 16)
    return browserid.jwt.load_key(alg, jwk)


class ReceiptJWT(browserid.jwt.JWT):
    """Class to override PyBrowserID's JWT parser"""

    def __init__(self, header, payload, signature, signed_data):
        self.header = header
        self.algorithm = header['alg']
        self.payload = payload
        self.signature = signature
        self.signed_data = signed_data

    def check_signature(self, key_data):
        """Do proper parsing of a JWS signed JWT as defined by
        http://tools.ietf.org/html/draft-ietf-jose-json-web-signature-01"""
        if not self.algorithm.startswith(key_data["alg"][0:1]):
            return False
        key = jwk_to_key(key_data, self.algorithm)
        return key.verify(self.signed_data, self.signature)


class ReceiptVerifier(local.LocalVerifier):

    def parse_jwt(self, data):
        return parse_jwt(data)

    def verify(self, assertion, audience=None, now=None):
        """Verify the certificate chain for the receipt
        """
        if now is None:
            now = int(time.time())

        # This catches KeyError and turns it into ValueError.
        # It saves having to test for the existence of individual
        # items in the various payloads.
        try:
            # Grab the assertion, check that it has not expired.
            # No point doing all that crypto if we're going to fail out anyway.
            certificates, assertion = unbundle_certs_and_assertion(assertion)
            assertion = self.parse_jwt(assertion)
            if assertion.payload["exp"] < now:
                raise ExpiredSignatureError(assertion.payload["exp"])

            # Parse out the list of certificates.
            certificates = [self.parse_jwt(c) for c in certificates]

            # Verify the entire chain of certificates.
            cert = self.verify_certificate_chain(certificates, now=now)

            # Check the signature on the assertion.
            if not self.check_token_signature(assertion, cert):
                raise InvalidSignatureError("invalid signature on assertion")
        except KeyError:
            raise ValueError("Malformed JWT")
        # Looks good!
        return True

    def check_token_signature(self, data, cert):
        return data.check_signature(cert.payload["jwk"][0])

    def verify_certificate_chain(self, certificates, now=None):
        """Verify a signed chain of certificates.

        This function checks the signatures on the given chain of JWT
        certificates.  It looks up the public key for the issuer of the
        first certificate, then uses each certificate in turn to check the
        signature on its successor.

        If the entire chain is valid then to final certificate is returned.
        """
        if not certificates:
            raise ValueError("chain must have at least one certificate")
        if now is None:
            now = int(time.time())
        root_issuer = certificates[0].payload["iss"]
        root_key = self.certs[root_issuer]
        current_key = root_key
        for cert in certificates:
            if cert.payload["exp"] < now:
                raise ExpiredSignatureError("expired certificate in chain")
            if not cert.check_signature(current_key):
                raise InvalidSignatureError("bad signature in chain by: '%s'" % current_key['kid'])
            current_key = cert.payload["jwk"][0]
        return cert

#
# MONKEY PATCH TIME!
#
browserid.certificates.fetch_public_key_orig = browserid.certificates.fetch_public_key
browserid.certificates.fetch_public_key = fetch_public_key
