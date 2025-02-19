# Environments

Olympia supports multiple environments, each configured by the ENV variable in the application settings. This ENV variable is read from the underlying system environment and determines various behaviors and configurations throughout the codebase.

Below is a table listing the environments that can be set via ENV. Details including the URL and a description for each environment are shown as placeholders:

| Environment | URL  | Description |
|-------------|------|-------------|
| build       | none | The build environment is used during the docker build process. It can be useful to know if code is executing during a docker build. |
| test        | none  | The test environment is used when running the application in a testing environment. It is the default environment when running `make test`. |
| local       | <http://olympia.test>  | The local environment is used when running the application locally. It is the default environment when running `make up`. |
| dev         | <https://addons-dev.allizom.org> | The dev environment is used when the application is deployed to dev after each commit to master. |
| stage       | <https://addons.allizom.org> | The stage environment is used when the application is deployed to stage after publishing a new release. |
| prod        | <https://addons.mozilla.org> | The prod environment is used when the application is deployed to prod after a stage release has been approved. |

## Usage

Sometimes there is some code that should only run in one specific environment, a set of environments or in all
but one environment.

```python
if settings.ENV == 'local':
    print('Running in local environment')
elif settings.ENV in ['dev', 'stage']:
    print('Running in dev or stage environment')
elif settings.ENV != 'prod':
    print('Running in non-production environment')
```

Using the `ENV` variable lets us tune the behavior of the application to the current environment.
