# Authentication

## Firefox Accounts

Firefox Accounts (FXA) is the authentication system used by addons-server.
In local development and in testing, we default to fake credentials which redirect
to a local fake auth page. If you define real credentials, you will be redirected
to fxa using the specified client id and secret.

### Local development

In local development, we default to fake credentials which redirect to a local
fake auth page. Fake credentials of '' are defined by default on the environment and read
into the FXA_CONFIG settings.

### Production environments

In production environments, we defined real FXA_CLIENT_ID and FXA_CLIENT_SECRET values
to be used on the corrresponding FXA servers.

### use_fake_fxa

A utility method is used to determine if we should use the fake or real fxa redirect.
This function only returns true if the environment is local/test and if the fake fxa client
id and secret are defined. This forces us to use real auth redirection in production environments.

### Getting real credentials for local development

You must contact the FxA team to get your own credentials for FxA stage.

To use these credentials, you can pass them to make up:

```bash
make up FXA_CLIENT_ID=<your-client-id> FXA_CLIENT_SECRET=<your-client-secret>
```

or set them in your environment (on the host machine, not inside the container):

```bash
export FXA_CLIENT_ID=<your-client-id>
export FXA_CLIENT_SECRET=<your-client-secret>

