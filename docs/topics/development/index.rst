===================
Development
===================

.. toctree::
   :maxdepth: 2

   introduction
   setup_and_configuration
   building_and_running_services
   makefile_commands
   testing_and_quality_assurance
   data_management
   dependency_management
   performance_and_optimization
   localization_and_internationalization
   troubleshooting_and_debugging
   tests
   dependencies
   docker
   error_pages
   testing
   style
   contributing
   branching
   vpn
   acl
   logging
   translations
   search
   docs
   waffle
   ../../../README.rst

Development
============

Welcome to the documentation for the **addons-server** project. This guide is designed to help developers quickly understand, set up, and manage the project's various services. By leveraging Docker Compose, we ensure modularity, isolation, and efficiency across development and testing environments. Here’s a concise overview of each section to get you up and running fast.

The **addons-server** uses Docker Compose to manage a multi-container setup, facilitating the handling and scaling of components like the web server, database, and search engine. BuildKit and Bake streamline the image-building process, and Docker layer caching ensures efficient builds. This documentation is organized into ten sections, providing practical instructions to help you get started quickly.

Sections Overview
=================

Introduction
============
   - **Overview**: Key features and purpose of the **addons-server** project.
   - **Architecture**: Summary of the Docker Compose-based architecture.
   - **Goals and Benefits**: Focus on modularity, isolation, and efficiency.

Setup and Configuration
========================
   - **Local Development Environment**: Steps to set up your local environment with `docker-compose.yml`.
   - **CI Environment**: Setting up the CI environment with `docker-compose.ci.yml` and GitHub Actions.
   - **Configuration Files**: Important environment variables and configuration files.

Building and Running Services
==============================
   - **Dockerfile Details**: Explanation of each stage in the Dockerfile.
   - **Build Process**: How to build Docker images using BuildKit and Bake.
   - **Managing Containers**: Commands to start, stop, and manage containers.

Makefile Commands
==================
   - **Overview**: Purpose of the Makefile in the project.
   - **Common Commands**: Key commands like `setup`, `up`, `down`, `test`, and `lint`.
   - **Specialized Commands**: Database management, debugging, and more.

Testing and Quality Assurance
==============================
   - **Testing Framework**: Overview of pytest-based testing.
   - **Running Tests**: How to run different types of tests.
   - **CI Integration**: Automating tests with GitHub Actions.

Data Management
================
   - **Database Initialization**: Setting up and managing the database.
   - **Data Export and Import**: Exporting and restoring MySQL data.
   - **Populating Data**: Scripts and commands for test data.

Dependency Management
======================
   - **Python Dependencies**: Managing Python dependencies with the Makefile and requirements files.
   - **Node.js Dependencies**: Handling Node.js dependencies with npm.

Performance and Optimization
=============================
   - **Docker Layer Caching**: Benefits and setup for Docker layer caching.
   - **Performance Testing**: Running performance tests and optimization tips.

Localization and Internationalization
======================================
   - **Locale Management**: Compiling and managing locales.
   - **Translation Management**: Handling translation strings and merging them.

Troubleshooting and Debugging
==============================
    - **Common Issues**: Solutions to common problems.
    - **Debugging Tools**: Tools and commands for effective debugging.

This guide aims to be your quick-reference manual for efficiently working with the **addons-server** pr
