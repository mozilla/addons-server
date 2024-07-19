target "olympia" {
  # Hardcoded values do not change
  context = "."
  dockerfile = "Dockerfile"
  platforms = ["linux/amd64"]

  output = [
    "type=docker"
  ]
}

# Default to building the local target
group "default" {
  targets = ["olympia"]
}
