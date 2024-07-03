# Allows setting default metadata via github actions
# https://github.com/docker/metadata-action?tab=readme-ov-file#bake-definition
target "docker-metadata-action" {}

# Control the build target (development/production)
variable "DOCKER_TAG" {
  default = "$DOCKER_TAG"
}

variable "DOCKER_TARGET" {
  default = "development"
}

variable "IMAGE_TAR_FILE" {
  default = "image.tar"
}

target "web" {
  # Allow github action metadata to populate tags/labels/annotations
  inherits = ["docker-metadata-action"]
  # Hardcoded values do not change
  context = "."
  dockerfile = "Dockerfile"
  platforms = ["linux/amd64"]

  # User controlled values that are directly configurable
  # We read the .env file which can read these values directly at buildtime
  tags = ["${DOCKER_TAG}"]
  target = "${DOCKER_TARGET}"

  output = [
    # Always export to a specified docker image file
    # This should be kept in sync with Makefile-os
    "type=docker,dest=${IMAGE_TAR_FILE}"
  ]
}

# Default to building the local target
group "default" {
  targets = ["web"]
}
