variable DOCKER_TAG {
  default = "$DOCKER_TAG"
}

target "olympia" {
  # Hardcoded values do not change
  context = "."
  dockerfile = "Dockerfile"
  platforms = ["linux/amd64"]

  output = [
    "type=docker"
  ]

  tags = [
    "${DOCKER_TAG}"
  ]
}

# Default to building the local target
group "default" {
  targets = ["olympia"]
}
