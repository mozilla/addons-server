#! /usr/bin/env python3

import argparse
import json
import re
import subprocess
import string

release_template_string = """
Current Release:
- author: @$release_author
- tag: $release_tag

Previous Release:
- author: $previous_release_author
- tag: [$previous_release_tag]($previous_release_url)

"""

release_sections = [
    "Blockers",
    "Before we push",
    "Before we start",
    "Before we promote",
    "After we're done",
]

changelog_commit_string = """
- [$sha]($url) (@$author)

$message
"""

release_changelog_string = """
## Changelog $title:
$changelog
"""

def get_commit(owner: str, repo: str, sha: str):
    output = subprocess.run([
        'gh', 'api',
        f'repos/{owner}/{repo}/commits/{sha}',
    ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(output.stdout.strip())

def get_changelog_url(
    owner: str = '{owner}',
    repo: str = '{repo}',
    release_tag: str = '{release_tag}',
    previous_tag: str = '{previous_tag}'
):
    return (
        f'https://github.com/{owner}/{repo}/compare/{previous_tag}...{release_tag}'
    )

def create_changelog(
        owner: str,
        repo: str,
        cherry_picks: list[str],
        release_tag: str,
        previous_tag: str,
):
    changelog = []

    for sha in cherry_picks:
        commit = get_commit(owner, repo, sha)
        changelog.append(
            string.Template(changelog_commit_string).substitute(
                sha=commit["sha"][:7],
                url=commit["html_url"],
                author=commit["author"]["login"],
                message=commit["commit"]["message"],
            )
        )

    title = str(repo).title()
    valid_tags = (release_tag and previous_tag)
    changelog_url = get_changelog_url(owner, repo, release_tag, previous_tag)

    return string.Template(release_changelog_string).substitute(
        title=(
            f'[{title}]({changelog_url})' if valid_tags
            else title
        ),
        changelog=(
            '\n'.join(changelog) if changelog
            else "\n<!-- Link to the tag comparison of the target tag and the previous tag -->"
        )
    )

def create_release_notes(
        release_tag: str,
        release_author: str,
        previous_release: dict,
        cherry_picks: list[str]
):
    release_template = string.Template(release_template_string)
    previous_release_tag = previous_release['tag_name']

    release_notes = release_template.substitute(
        release_author=release_author,
        release_tag=release_tag,
        previous_release_author=previous_release['author']['login'],
        previous_release_tag=previous_release_tag,
        previous_release_url=previous_release['html_url'],
    )

    for section in release_sections:
        release_notes += f'\n## {section}\n'

    release_notes += create_changelog(
        'mozilla',
        'addons-server',
        cherry_picks,
        release_tag,
        previous_release_tag,
    )

    release_notes += create_changelog(
        'mozilla',
        'addons-frontend',
        [],
        None,
        None,
    )

    return release_notes

def create_release(
    release_tag: str,
    release_author: str,
    previous_release: dict,
    cherry_picks: list[str]
):
    release_notes = create_release_notes(
        release_tag,
        release_author,
        previous_release,
        cherry_picks,
    )
    return True


def get_release(tag: str = None):
    path = f'tags/{tag}' if tag else 'latest'

    try:
      output = subprocess.run([
          'gh', 'api',
          '-H', 'Accept: application/vnd.github+json',
          '-H', 'X-GitHub-Api-Version: 2022-11-28',
          f'/repos/mozilla/addons-server/releases/{path}',
      ],
          capture_output=True,
          text=True,
          check=True,
      )
      return json.loads(output.stdout.strip())
    except subprocess.CalledProcessError as e:
      if 'HTTP 404' in e.stderr:
          return None
      raise e

def get_tag_version(tag: str, version: int):
    return f'{tag}.{version}'

def main(release_tag: str, release_author: str, minor: bool, cherry_picks: list[str]):
    if not release_tag or not re.match(r'^\d{4}\.\d{2}\.\d{2}$', release_tag):
        raise ValueError(f'Invalid tag: {release_tag}')

    is_release_tag = bool(get_release(release_tag))

    previous_tag = None
    next_tag = None

    if minor:
        if not is_release_tag:
            raise ValueError(
                f'Cannot create minor release for {release_tag} because it does not exist.'
            )
        if not cherry_picks:
            raise ValueError(
                f'Cannot create minor release for {release_tag}. Missing cherry picks.'
            )

        current_version = 1
        previous_tag = release_tag
        next_tag = get_tag_version(release_tag, current_version)

        while get_release(next_tag):
            previous_tag = next_tag
            current_version += 1
            next_tag = get_tag_version(release_tag, current_version)

    else:
        if not release_author:
            raise ValueError(
                f'Cannot create major release {release_tag} because no author is provided.'
            )
        if is_release_tag:
            raise ValueError(f'Cannot create major release {release_tag} because it already exists.')

        previous_tag = get_release()['tag_name']
        next_tag = release_tag

    return create_release(
        next_tag,
        release_author,
        get_release(previous_tag),
        cherry_picks,
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("version", type=str)
    parser.add_argument("--minor", action="store_true", default=False)
    parser.add_argument("--author", type=str, required=False)
    parser.add_argument("--cherry-pick", type=str, required=False, default="")
    args = parser.parse_args()

    main(
        args.version,
        args.author,
        args.minor,
        args.cherry_pick.split(',') if args.cherry_pick else [],
    )
