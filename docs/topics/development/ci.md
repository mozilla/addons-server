# CI

This document will explain roughly how CI should work for addons-server.

## Build

We use docker and docker-compose to run our app locally, and in CI. All CI jobs should run against a built docker image.
This ensures that what we are testing in CI accurately reflects what will be deployed to production. Similarly, what
we develop against should be as close to the same.

We have a reusable `build-docker` github action to build our docker image. Add it to a workflow and either load or push the image.

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - id: build
        uses: ./.github/actions/build-docker
        with:
          target: development
          push: true
          username: ${{ secrets.DOCKER_USER }}
          password: ${{ secrets.DOCKER_PASS }}
```

This will build the docker image to the `development` stage and push the image to dockerhub.

> NOTE: you can either push or load the image. If you plan to run commands against the image, set push to false.
> NOTE: You can secify either "production" or "development" for stages. This controls which dependencies will be installed in the image but otherwise the image is identical

## Test

Once you've built the image, you can run commands against the web container using the `run-docker` action.

```yaml
      - name: Test
        uses: ./.github/actions/run-docker
        with:
          version: ${{ steps.build.outputs.version }}
          up: 'web mysql'
          command: |
            pytest
```

This will spin up the `web` and `mysql` services and run `pytest` on the web container.

> NOTE: we are referencing the version from a previous build step to test against a container we built in CI. you can reference any image that is pulled `docker images` this action will explicitly NOT pull images to avoid accidental versions running.

## Publish

As specified above you can publish images using the `build-docker` action. The action uses a heuristic to determine the image version.

- branches: will tag the branch name `my-branch`
- PR: will tag the pr number `pr-123`
- Tag: a git tag will tag the tag `04.12.2023`
- it is impossible to tage `latest` currently.
