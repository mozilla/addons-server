#!/usr/bin/python
"""
This script is for setting up OAuth credentials for Google Analytics.

To use:
Visit https://code.google.com/apis/console/ and select "API Access".
If a client ID for a "web application" hasn't been created, add one.
Click "Download JSON" in the box containing information about that client ID.
Run this script with the filename of the downloaded JSON.
Paste the printed credentials into the Django settings file.
"""

import pprint
import sys

from oauth2client.client import flow_from_clientsecrets, Storage
from oauth2client.tools import run

if len(sys.argv) != 2:
    print "usage: auth_google_analytics.py <client secrets filename>"
    sys.exit(1)

CLIENT_SECRETS = sys.argv[1]

MISSING_CLIENT_SECRETS_MESSAGE = ("%s is missing or doesn't contain secrets "
                                  "for a web application" % CLIENT_SECRETS)

FLOW = flow_from_clientsecrets(
    CLIENT_SECRETS,
    scope='https://www.googleapis.com/auth/analytics.readonly',
    message=MISSING_CLIENT_SECRETS_MESSAGE)


s = Storage()
s.put = lambda *a, **kw: None
credentials = run(FLOW, s)

bits = dict([(name, getattr(credentials, name)) for name in
             ('access_token', 'client_id', 'client_secret',
              'refresh_token', 'token_expiry', 'token_uri',
              'user_agent')])
print 'GOOGLE_ANALYTICS_CREDENTIALS = ',
pprint.pprint(bits)
