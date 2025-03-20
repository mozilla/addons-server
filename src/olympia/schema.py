from drf_spectacular.extensions import OpenApiAuthenticationExtension


# Add Extensions to the Schema, so we can handle scenarios where introspection
# is not possible (like when using the SessionIDAuthentication).
# https://drf-spectacular.readthedocs.io/en/latest/customization.html#step-5-extensions


class SessionIDAuthenticationSchema(OpenApiAuthenticationExtension):
    target_class = 'olympia.api.authentication.SessionIDAuthentication'
    name = 'SessionIDAuthentication'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'apiKey',
            'in': 'header',
            'name': 'Authorization',
            'description': 'pass the sessionId cookie as "Session {token}"',
        }


class JWTKeyAuthenticationSchema(OpenApiAuthenticationExtension):
    target_class = 'olympia.api.authentication.JWTKeyAuthentication'
    name = 'JWTKeyAuthentication'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'apiKey',
            'in': 'header',
            'name': 'Authorization',
            'description': 'pass the JWT token as "JWT {token}"',
        }
