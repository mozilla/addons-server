# Introduction to the Development Section

Welcome to the development section of the **addons-server** documentation. This guide is designed to help developers quickly understand, set up, and manage the project's various services. By leveraging Docker Compose, we ensure modularity, isolation, and efficiency across development and testing environments. Here’s a concise overview of each section to get you up and running fast.

## Sections Overview

### Setup and Configuration

[link](./setup_and_configuration.md)

- **Local Development Environment**: Steps to set up your local environment with `docker-compose.yml`.
- **CI Environment**: Setting up the CI environment with `docker-compose.ci.yml` and GitHub Actions.
- **Configuration Files**: Important environment variables and configuration files.

### Building and Running Services

[link](./building_and_running_services.md)

- **Dockerfile Details**: Explanation of each stage in the Dockerfile.
- **Build Process**: How to build Docker images using BuildKit and Bake.
- **Managing Containers**: Commands to start, stop, and manage containers.

### Makefile Commands

[link](./makefile_commands.md)

- **Overview**: Purpose of the Makefile in the project.
- **Common Commands**: Key commands like `setup`, `up`, `down`, `test`, and `lint`.
- **Specialized Commands**: Database management, debugging, and more.

### Testing and Quality Assurance

[link](./testing_and_quality_assurance.md)

- **Code Quality and Linting**: Using `ruff` and `prettier` to format and lint code.
- **Build Verification**: Ensuring builds are consistent between local and CI environments.
- **Running Tests**: How to run different types of tests using `pytest`.

### Data Management

[link](./data_management.md)

- **Persistent Data Volumes**: Storing MySQL data.
- **Data Export and Import**: Exporting and restoring MySQL data.
- **Database Initialization**: Setting up and managing the database.

### Dependency Management

[link](./dependency_management.md)

- **Python Dependencies**: Managing Python dependencies with the Makefile and requirements files.
- **Node.js Dependencies**: Handling Node.js dependencies with npm.

### Performance and Optimization

[link](./performance_and_optimization.md)

- **Docker Layer Caching**: Benefits and setup for Docker layer caching.
- **Performance Testing**: Running performance tests and optimization tips.

### Localization and Internationalization

[link](./localization_and_internationalization.md)

- **Locale Management**: Compiling and managing locales.
- **Translation Management**: Handling translation strings and merging them.

### Troubleshooting and Debugging

[link](./troubleshooting_and_debugging.md)

- **Common Issues**: Solutions to common problems.
- **Debugging Tools**: Tools and commands for effective debugging.

### Error Pages

[link](./error_pages.rst)

- **Accessing and Customizing**: Information on the standard error pages used in the application.

This guide aims to be your quick-reference manual for efficiently working with the **addons-server** project. Each section provides practical instructions and insights to help you set up, develop, and maintain the project effectively.

## Style

[link](./style.rst)

## Contributing

[link](./contributing.rst)

## Branching

[link](./branching.rst)

## VPN

[link](./vpn.rst)

## ACL

[link](./acl.rst)

## Logging

[link](./logging.rst)

## Search

[link](./search.rst)

## Docs

[link](./docs.rst)

## Waffle

[link](./waffle.md)
