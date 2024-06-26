##### Important information for maintaining this Dockerfile ########################################
# Read the docs/topics/development/docker.md file for more information about this Dockerfile.
####################################################################################################

FROM python:3.11-slim-bookworm as olympia

# Set shell to bash with logs and errors for build
SHELL ["/bin/bash", "-xue", "-c"]

ENV OLYMPIA_UID=9500
RUN <<EOF
groupadd -g ${OLYMPIA_UID} olympia
useradd -u ${OLYMPIA_UID} -g ${OLYMPIA_UID} -s /sbin/nologin -d /data/olympia olympia
EOF

# give olympia access to the HOME directory
ENV HOME /data/olympia
WORKDIR ${HOME}
RUN chown -R olympia:olympia ${HOME}

FROM olympia as base

RUN echo "base"

FROM base as sources

# Copy the rest of the source files from the host
COPY --chown=olympia:olympia . ${HOME}

# Set shell back to sh until we can prove we can use bash at runtime
SHELL ["/bin/sh", "-c"]

FROM sources as development

RUN echo "development"

FROM sources as production

RUN echo "production"


