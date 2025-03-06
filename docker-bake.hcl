group "default" {
  targets = ["web"]
}

variable DOCKER_BUILD {}
variable DOCKER_COMMIT {}
variable DOCKER_TAG {}
variable DOCKER_TARGET {}
variable DOCKER_VERSION {}
variable OLYMPIA_DEPS {}

target "web" {
  context = "."
  dockerfile = "Dockerfile"
  target = "${DOCKER_TARGET}"
  tags = ["${DOCKER_TAG}"]
  platforms = ["linux/amd64"]
  args = {
    DOCKER_BUILD = "${DOCKER_BUILD}"
    DOCKER_COMMIT = "${DOCKER_COMMIT}"
    DOCKER_TAG = "${DOCKER_TAG}"
    DOCKER_TARGET = "${DOCKER_TARGET}"
    DOCKER_VERSION = "${DOCKER_VERSION}"
    DOCKER_SOURCE = "https://github.com/mozilla/addons-server"
    OLYMPIA_DEPS = "${OLYMPIA_DEPS}"
  }
  pull = true

  output = [
    "type=docker",
  ]

}
