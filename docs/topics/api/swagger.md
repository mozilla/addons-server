# Swagger API Documentation

This document covers the use of Swagger (OpenAPI) in the addons.mozilla.org API.

## What is Swagger/OpenAPI?

[Swagger](https://swagger.io/) (now known as [OpenAPI](https://www.openapis.org/)) is a specification for documenting RESTful APIs. It allows you to describe your entire API, including:

- Available endpoints and operations (GET, POST, PUT, DELETE, etc.)
- Input and output parameters for each operation
- Authentication methods
- Contact information, license, terms of use, and other information

The OpenAPI specification is language-agnostic and machine-readable, making it easy to generate documentation, client libraries, and server stubs in various programming languages.

## Using Swagger UI in AMO

We use the [drf-spectacular](https://github.com/tfranzel/drf-spectacular) library to generate the swagger.json file
and serve the Swagger UI endpoints.

You can access these interfaces at the following URLs (replace `<version>` with the API version you're working with, e.g., `v5`):

- `http://olympia/api/v5/swagger/` - Interactive Swagger UI documentation
- `http://olympia/api/v5/redoc/` - ReDoc documentation (alternative UI)
- `http://olympia/api/v5/schema/` - Raw schema definition

You can also append `?format=json` or `?format=yaml` to the schema URL to view the schema directly in your browser instead of downloading it:

```bash
http://olympia/api/v5/schema/?format=json
```

> [!NOTE]
> The swagger UI is not available in production environments (yet).

### Exploring with Swagger UI

Swagger UI provides an interactive interface to:

1. Browse all available endpoints
2. Read documentation for each endpoint
3. Try out API calls directly from the browser
4. See request and response formats
5. View models and schemas

The interface makes it easier to understand how to use the API without needing to read through extensive documentation.

## Generating a Swagger Client

The project includes a script to generate client libraries from the Swagger/OpenAPI definition. This allows you to interact with the API in your preferred programming language with typed interfaces and built-in models.

First you should generate the swagger.json file. We have a make command for this:

```bash
make swagger
```

To generate a client library, use the `swagger_client` command:

```bash
make swagger_client
```

This generates a TypeScript client in the `swagger-client` directory.
The script uses Docker with the OpenAPI Generator CLI tool.

### Using the client

Here is an example of an authenticated request using the client. First create a JWT token (more details):

```typescript
import jwt from 'jsonwebtoken';

const jwtSecret = 'secret';
const jwtIssuer = 'user:X';

const issuedAt = Math.floor(Date.now() / 1000);
const payload = {
  iss: jwtIssuer,
  jti: Math.random().toString(),
  iat: issuedAt,
  exp: issuedAt + 60,
};

const token = jwt.sign(payload, jwtSecret, {
  algorithm: 'HS256',
});
```

Now configure the client to use the JWT authentication method:

```typescript
import * as api from './swagger-client';

const config = new api.Configuration({
  basePath: 'http://olympia.test',
  apiKey: (name) => `JWT ${token}`,
});

const addonsApi = new api.AddonsApi(config);

// result will have the type api.Addon which is a typescript interface
// containing the types of the swagger definition for that model
const result = await addonsApi.addonsAddonRetrieve({id: '1'});
```

What is really powerful is that the client is typesafe automatically,
returning an interface based on the swagger definition.

### TODOs

- [X] make the client use native fetch instead of whatwg-fetch
- [ ] validate the swagger schema, we have > 100 warnings and several errors
- [ ] publish the client to npm

## Additional Resources

- [OpenAPI Specification](https://spec.openapis.org/oas/latest.html)
- [Swagger.io Documentation](https://swagger.io/docs/)
- [OpenAPI Generator](https://github.com/OpenAPITools/openapi-generator)
- [Swagger UI](https://swagger.io/tools/swagger-ui/)
- [ReDoc](https://github.com/Redocly/redoc)

For more information about the API itself, refer to the [API Overview](./overview.rst) and other API documentation.
