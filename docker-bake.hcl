group "default" {
  targets = ["web"]
}

variable DOCKER_BUILD {}
variable DOCKER_COMMIT {}
variable DOCKER_VERSION {}
variable DOCKER_TARGET {}
variable DOCKER_TAG {}

variable HOST_UID {}

# User defined function to check if the target is a local build
function "endswith" {
  params = [str, suffix]
  result = (
    strlen(suffix) <= strlen(str) &&
    substr(str, strlen(str) - strlen(suffix), strlen(suffix)) == suffix
  )
}


target "web" {
  context = "."
  dockerfile = "Dockerfile"
  target = "${DOCKER_TARGET}"
  tags = ["${DOCKER_TAG}"]
  platforms = ["linux/amd64"]
  args = {
    DOCKER_COMMIT  = "${DOCKER_COMMIT}"
    DOCKER_VERSION = "${DOCKER_VERSION}"
    DOCKER_BUILD   = "${DOCKER_BUILD}"
    OLYMPIA_UID    = "${endswith("${DOCKER_TAG}", ":local") ? HOST_UID : null}"
  }
  pull = true

  output = [
    "type=docker",
  ]

}
