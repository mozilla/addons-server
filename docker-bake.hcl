variable DOCKER_TAG {
  default = "$DOCKER_TAG"
}

target "olympia" {
  # Hardcoded values do not change
  context = "."
  dockerfile = "Dockerfile"
  platforms = ["linux/amd64"]

  tags = [
    "${DOCKER_TAG}"
  ]
}

# Default to building the local target
group "default" {
  targets = ["olympia"]
}
