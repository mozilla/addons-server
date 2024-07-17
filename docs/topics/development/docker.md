# Docker

## The Dockerfile

Our Dockerfile is used in both production and development environments, however it is not always and not entirely used in CI (for now at least).

The Dockerfile builds addons-server and runs using docker-compose by specifying the latest image pushed to dockerhub. Keep in mind during local development you are likely not running the current image in your git repository but the latest push to master in github.

### Best Practices for the Dockerfile

- Use as few instructions as possible
- Split long running tasks into distinct stages to improve caching/concurrency
- Prefer --mount=type=bind over COPY for files that are needed for a single command

  > bind mounts files as root/docker user, so run the stage from base and chown them to olympia.
  > bind mounts do not persist data, so if you modify any files, they will **not** be in the final layer.

- If you do use COPY for files that are executed, prefer copying individual files over directories.

  > The larger the directory, the more likely it is to have false cache hits.
  > Link: <https://github.com/moby/moby/issues/33107>

- Use --mount=type=cache for caching caches npm/pip etc.

  > cache mounts are not persisted in CI due to an existing bug in buildkit. Link: <https://github.com/moby/buildkit/issues/1512>

- Delay copying source files until the end of the Dockerfile to imrove cache validity

## Building locally

To build the Dockerfile locally, run the following command:

```bash
make build_docker_image
```

This will build the Dockerfile locally with buildkit and tag it as _addons-server-test_ by default. You can control several parameters including the tag and platform. This can be very useful if you are testing a new image or want to test a new platform.

We utilize buildkit layer and mount caching to build extremely efficiently. There are more improvements we can make.

## Clearing cache

Because we use a custom builder to take full advantage of buildkit mount caching clearing your cache means clearing
the specific builder cache we use, not the docker cache.

Do:

```bash
docker builder prune
```

Don't do:

```bash
docker system prune
```
