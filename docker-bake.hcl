group "default" {
  targets = ["web"]
}

variable DOCKER_BUILD {}
variable DOCKER_COMMIT {}
variable DOCKER_VERSION {}
variable DOCKER_TARGET {}
variable DOCKER_TAG {}

target "web" {
  context = "."
  dockerfile = "Dockerfile"
  target = "${DOCKER_TARGET}"
  tags = ["${DOCKER_TAG}"]
  platforms = ["linux/amd64"]
  args = {
	DOCKER_COMMIT = "${DOCKER_COMMIT}"
	DOCKER_VERSION = "${DOCKER_VERSION}"
	DOCKER_BUILD = "${DOCKER_BUILD}"
  }
  pull = true
  cache-to = [
    "type=gha,mode=max,scope=mozilla/addons-server/web"
  ]
  cache-from = ["type=gha,scope=mozilla/addons-server/web"]

  output = [
    "type=docker",
  ]

}
