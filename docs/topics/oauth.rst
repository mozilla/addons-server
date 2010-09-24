=====
OAuth
=====

The new API (``/api/2/*``) is powered by Piston and authentication is provided
for via OAuth.  OAuth is a means for users to grant permissions to a third
party application to act on their behalf without supplying a username and
password.

The OAuth Dance
---------------

The OAuth "dance" involves a number of steps:

1. **Requesting an OAuth Request Token.**  The third party app (e.g. Flight
   Deck) requests a *Request Token* from the website (e.g. AMO).
2. The app sends the user with the *Request Token* to an authorization page.
3. The app requests an *Access Token* with the user-authorized *Request Token*.

Each of these reuqests must contain various OAuth headers, request parameters
and be signed in a specific manner.

This is detailed in our api tests in ``_oauth_flow``.
