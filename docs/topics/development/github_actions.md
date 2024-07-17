# Github Actions

The **addons-server** project uses GitHub Actions to automate testing and building processes in the CI environment.
The CI pipeline broken into workflows, jobs and steps that run on containers in github's cloud environment.
All workflows are defined in the _.github/workflows_ directory.

## Overview

Here’s an overview of the existing CI workflows and their architecture:

Workflows are run on events. Events determine the reason for running the workflow.
A workflow can be triggered by multiple events. {ref}`Learn more <configuration>` about configuring events below.

Generally, we run addons-server inside it's own docker container. This means every workflow generally follows the same pattern.

### Build the docker image

Run the {ref}`build-docker <actions_build_docker>` action to build the docker image from the current ref in github.
This action can be configured to your needs to build, push, and or upload the image to be used later.
The build passing is itself a good first step to test the code, and you can further test after the image is ready.

### Run the docker image

Define a job that uses the {ref}`run-docker <actions_run_docker>` reusable action. This action runs our docker compose
project in the CI container allowing you to exeucte the same commands you would run locally.
This is the foundation of nearly every test we have in CI.

(configuration)=
## Configuration

- links to docs for github action configuration and event payloads and syntax
- reusable actions have a _ prefix
- prefer reusable workflows over actions

### Workflows

Workflows are the top level configuration object for github actions. Here is an example:

```yaml
name: Set a name

on:
  pull_request:
    branches:
    - master

concurrency:
  group: ${{ github.workflow }}-${{ github.event_name}}-${{ github.ref}}-${{ toJson(inputs) }}
  cancel-in-progress: true

jobs:
  job1:
    ...
```

> Important: Always define the most specific event triggers possible
> and always set concurrency groups to prevent too many instances of a workflow running simultaneously

### Reusable Workflows

We use reusable workflows to enable calling one workflow from another.
This allows better encapsulation of a set of logic that might itself require multiple jobs, matrix jobs
or direct access to built in context like secrets. Otherwise they are conceptually similar to {ref}`reusable actions <reusable_actions>`.

Reusable workflows should define a constant in their _concurrency:group_ to prevent deadlock with their triggering workflow.

```yaml
concurrency:
  group: static-${{ github.workflow }}...
```

The unique and static key prevents the worfklow (which will match the calling workflow) concurrency group from over matching.

(_test_yml)=
#### _test.yml

[link](../../../.github/workflows/_test.yml)

Our main testing workflow runs a suite of tests verifying the docker image and django code within are running as expected.

(_test_main_yml_)=
#### _test_main.yml

[link](../../../.github/workflows/_test_main.yml)

This workflow is a branch of our _test.yml workflow, running specifically the main pytest suite.
It is split to its own workflow because it runs via a matrix strategy and spins up a lot of jobs.

(reusable_actions)=
### Reusable Actions

Reusable actions are like reusable workflows but they do not run on their own runner,
but directly as a step in a given workflow runner container.

(actions_context)=
#### context

[link](../../../.github/actions/context/action.yml)

This action provides additional context based on the _github_ context object. Most importantly it helps us determine
if we are running on a fork or if various meta events (releast_tag, release_master) match the current context.
These contextual values are relevent globally and should return the same values no matter where context is called,
so context runs as an action and accepts no inputs.

(actions_build_docker)=
#### build-docker

[link](../../../.github/actions/build-docker/action.yml)

The main action to build our docker image.
It builds a docker image based on the current state of the code, setting the appropriate metadata
based on context.

(actions_run_docker)=
#### run-docker

[link](../../../.github/actions/run-docker/action.yml)

The main action to run our docker compose project. This action is configurable to run a specified command, with specified services,
and even configurable compose file. Importantly this action will pull an image via the digest or version, and if it cannot find the image
will build it locally to run the current state of the codebase.

(actions_login_docker)=
#### login-docker

[link](../../../.github/actions/login-docker/action.yml)

Login to dockerhub to push the publically available docker image. This action authenticates using repository secrets so cannot
be used in forks. It also returns the registry and image properties expected by dockerhub in the tag.

(actions_login_ga)=
#### login-gar

[link](../../../.github/actions/login-gar/action.yml)

Login to [GAR][gar_link] (Google Artifact Registry) to push the production docker image.
This action authenticates using repository secrets so cannot be used in forks.
It also returns the registry and image properties expected by dockerhub in the tag.

### Actions vs Workflows

Some of our reusable logic is in reusable actions and some in workflows. There are some important tradeoffs worth mentioning
that inform the decision for which to choose in a particular use case.

1. Actions run ON a job, workflows run AS a job. If the logic you need requires context from the calling job,
like authentication credentials, created files, etc, then an action is the way to go. Workflows are great for code isolation
or if your logic might benefit itself from splitting to multiple jobs.

2. Actions are steps. Actions run as a step ON a job (see above) so they checkout code, they cannot access secrets,
they cannot define their own runner or set timeouts or environment variables. Actions should be for very isolated logic
that really executes a single step in a job.

3. Workflows have their own concurrency considerations. When using reusable workflows the concurrency group
can clash with the current workflow or even (if not careful) with other workfllows. Be careful and set strong concurrency groups.

4. Workflow jobs are collapsed in the github action UI. This is a nice feature if you need to trigger many jobs in parallel,
like {ref}`test_main <_test_main_yml_>` does. Each of the jobs are collapsible in the UI making it easier to clean up the view.

For the most part actions are simpler and should be the go to method for extacting reusable logic. Workflows are nice
when you need to organize the logic into multiple jobs or require extreme isolation from the rest of the workflow.

## Gotchas

- workflow_dispatch and workflow_call inputs should be identical

Best practice should be to define all _reusable workflows with both a _workflow_dispatch_ and _workflow_call_ event trigger.
The inputs for each should be identical. This allows testing and otherwise triggering reusable workflows directly or via
another workflow with the same parameters and expectations.

- github object contents depend on the event triggering the workflow

One of the reasons we have the {ref}`context action <actions_context>` is because the information embedded in the github
object depends on the event that triggered a workflow, making finding a certain piece of information depend on the 'context'.
Be careful using the github object directly as you must consider many edge cases. Consult the context action and potentially
introduce an important contextual value their so it can be made consistent across different contexts.

- github converts job/step/workflow outputs to string regardless of the underlying data type

Even if you define an input with a specific datatype, outputs for steps, jobs and reusable workflows are all converted to strings.
This is important when passing values from outputs to inputs as the data type might not actually be what you want or expect.

Use:

```yaml
uses: <action>
with:
  number: ${{ fromJSON(output.value) }}
```

to convert values back into numbers/booleans.

- secrets are not available for workflows running on forks.

Github actions prevents forks from accessing secrets, so workflows that use secrets should be configured to either
not rely on secrets or have fallback behaviour in place.

- use context action to define global context

Most global context should be defined in the {ref}`context <actions_context>` action instead of directly in workflows.

- prevent invalid workflow configurations

When reusable workflows are passed invalid outputs, github will silently fail the workflow, to prevent this you should always
check the outcome of reusable workflow calls.

[gar_link]: https://cloud.google.com/artifact-registry
