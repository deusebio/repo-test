# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Utility for running the migration action, primarily for testing purposes."""

import argparse
import json
import logging
import sys
from enum import Enum
from pathlib import Path
from typing import Tuple

from src.gatekeeper import index as index_module
from src.gatekeeper import navigation_table
from src.gatekeeper.constants import DOCUMENTATION_FOLDER_NAME, DOCUMENTATION_TAG
from src.gatekeeper.discourse import Discourse, create_discourse
from src.gatekeeper.repository import (
    ACTIONS_PULL_REQUEST_TITLE,
    DEFAULT_BRANCH_NAME,
    Client,
    create_repository_client,
)

from .common import (
    E2E_BASE,
    E2E_BRANCH,
    E2E_SETUP,
    close_pull_request,
    general_cleanup,
    with_result,
)


class Action(str, Enum):
    """The actions the utility can take.

    Attrs:
        PREPARE: Prepare discourse pages before running the migration.
        CHECK_PULL_REQUEST: Check that the migration pull request was created.
        CREATE_CONFLICT: create a simple conflict by editing both local and discourse sources.
        RESOLVE_CONFLICT: resolve a conflict by making sure that local and discourse versions
            matches.
        MERGE_FEATURE: simulate the remote merging of a feature.
        CLEANUP: Delete discourse pages and migration pull request and branch after the migration.
    """

    PREPARE = "prepare"
    CHECK_PULL_REQUEST = "check-pull-request"
    CREATE_CONFLICT = "create-conflict"
    RESOLVE_CONFLICT = "resolve-conflict"
    MERGE_FEATURE = "merge-feature"
    CLEANUP = "cleanup"


def main() -> None:
    """Execute requested migration action.

    Raises:
        NotImplementedError: if an action was received for which there is no imlpementation.
    """
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(
        prog="MigrationTestSupport",
        description="Support functions for the migration testing.",
    )
    parser.add_argument(
        "discourse_config", help="The discourse configuration used to create the pages"
    )
    parser.add_argument(
        "--action", help="Action to run", choices=tuple(action.value for action in Action)
    )
    parser.add_argument("--github-token", help="Github token to setup repository")
    args = parser.parse_args()
    discourse_config = json.loads(args.discourse_config)

    discourse = create_discourse(**discourse_config)
    repository = create_repository_client(args.github_token, Path.cwd())

    match args.action:
        case Action.PREPARE.value:
            prepare(repository, discourse)
            sys.exit(0)
        case Action.CREATE_CONFLICT.value:
            with_result(create_conflict(repository, discourse))
        case Action.RESOLVE_CONFLICT.value:
            with_result(resolve_conflict(repository, discourse))
        case Action.CHECK_PULL_REQUEST.value:
            with_result(check_pull_request(repository))
        case Action.MERGE_FEATURE.value:
            with_result(merge_feature_branch(repository))
        case Action.CLEANUP.value:
            with_result(cleanup(repository, discourse))
        case _:
            raise NotImplementedError(f"{args.action} has not been implemented")


def prepare(repository: Client, discourse: Discourse) -> bool:
    """Prepare the stage for the tests.

    Args:
        repository: Client repository to used
        discourse: Discourse client class

    Returns:
        boolean representing whether the preparation was successful.
    """
    assert discourse

    repository._git_repo.git.fetch("--all")  # pylint: disable=W0212

    repository.create_branch(E2E_BASE, E2E_SETUP).switch(E2E_BASE)

    repository._git_repo.git.push("-f", "-u", "origin", E2E_BASE)  # pylint: disable=W0212

    close_pull_request(repository)

    if repository.tag_exists(DOCUMENTATION_TAG):
        logging.info("Removing tag %s", DOCUMENTATION_TAG)
        repository._git_repo.git.tag("-d", DOCUMENTATION_TAG)  # pylint: disable=W0212
        repository._git_repo.git.push(  # pylint: disable=W0212
            "--delete", "origin", DOCUMENTATION_TAG
        )

    return True


def check_pull_request(repository: Client) -> bool:
    """Check whether the pull request was opened correctly.

    Args:
        repository: Client repository to used

    Returns:
        boolean representing whether the pull request creation was successful.
    """
    test_name = "check-pull-request"

    # Check the pull request exists
    pull_request = repository.get_pull_request(DEFAULT_BRANCH_NAME)
    if not pull_request:
        logging.error(
            "%s check failed, migration pull request %s not created",
            test_name,
            ACTIONS_PULL_REQUEST_TITLE,
        )
        return False

    # Log all the issues that were found
    success = True

    # Check the head and base branch
    if pull_request.head.ref != DEFAULT_BRANCH_NAME:
        logging.error(
            "%s check failed, migration pull request head branch is not as expected, "
            "head branch: %s, expected: %s",
            test_name,
            pull_request.head,
            DEFAULT_BRANCH_NAME,
        )
        success = False

    logging.info("%s check succeeded", test_name)
    return success


def get_test_topic_file(repository: Client, discourse: Discourse) -> Tuple[Path, str]:
    """Centralize retriveal of one specific files to be used across actions.

    Args:
        repository: Client repository to used
        discourse: Discourse client class

    Raises:
        ValueError: when the index retrieved from the repository is empty

    Returns:
        Tuple with (path of the files in the repository, link to the topic in Discourse)
    """
    index = index_module.get(
        metadata=repository.metadata,
        base_path=repository.base_path,
        server_client=discourse,
    )

    if not index.server:
        raise ValueError("index server cannot be none.")

    table_rows = navigation_table.from_page(page=index.server.content, discourse=discourse)

    row = [row for row in table_rows if "t-overview" in row.path][0]

    file_path = Path(".").joinpath(DOCUMENTATION_FOLDER_NAME, *row.path[:-1], f"{row.path[-1]}.md")

    if not row.navlink.link:
        raise ValueError("Link in the row of the navigation table must be populated.")

    return file_path, row.navlink.link


def create_conflict(repository: Client, discourse: Discourse) -> bool:
    """Creating a conflict by mismatching Github and Discourse sources.

    Args:
        repository: Client repository to used
        discourse: Discourse client class

    Returns:
        boolean representing whether the operation was successful.
    """
    repository._git_repo.git.fetch("--all")  # pylint: disable=W0212
    repository.switch(E2E_BASE)

    file_path, topic_url = get_test_topic_file(repository, discourse)

    source = file_path.read_text(encoding="utf-8").split("\n\n[E2E Test]")[0]

    repository.create_branch(E2E_BRANCH, E2E_BASE).switch(E2E_BRANCH)
    file_path.write_text(source + "\n\n[E2E Test] Conflict in PR", encoding="utf-8")
    repository.update_branch("Modification of documentation", force=True)

    discourse.update_topic(
        url=topic_url,
        content=source + "\n\n[E2E Test] Conflict in Community contribution",
        edit_reason="Modification proposed by community",
    )

    return True


def resolve_conflict(repository: Client, discourse: Discourse) -> bool:
    """Resolve conflicts by aligning both Github and Discourse.

    Args:
        repository: Client repository to used
        discourse: Discourse client class

    Returns:
        boolean representing whether the operation was successful.
    """
    file_path, topic_url = get_test_topic_file(repository, discourse)

    source = (
        file_path.read_text(encoding="utf-8").split("\n\n[E2E Test]")[0]
        + "\n\n[E2E Test] Resolved Conflict in PR"
    )

    file_path.write_text(source, encoding="utf-8")
    repository.update_branch("Conflict resolution", force=True)

    discourse.update_topic(
        url=topic_url, content=source, edit_reason="Conflict resolution in Discourse"
    )

    return True


def merge_feature_branch(repository: Client) -> bool:
    """Merge the feature branch by branch rebasing.

    Args:
        repository: Client repository to used

    Returns:
        boolean representing whether the pull request creation was successful.
    """
    repository._git_repo.git.fetch("--all")  # pylint: disable=W0212

    # If update was successful and a PR was created, we simulate the merge remotely
    repository.switch(E2E_BRANCH)

    with repository.create_branch(E2E_BASE, E2E_BRANCH).with_branch(E2E_BASE) as repo:
        repo._git_repo.git.push(  # pylint: disable=W0212
            "--set-upstream", "-f", "origin", E2E_BASE
        )

    repository.switch(E2E_BASE)

    return True


def cleanup(repository: Client, discourse: Discourse) -> bool:  # noqa: C901
    """Clean up testing artifacts on GitHub and Discourse.

    Args:
        repository: Client repository to used
        discourse: Discourse client class

    Returns:
        Whether the cleanup succeeded.
    """
    result = True

    file_path, topic_url = get_test_topic_file(repository, discourse)

    source = file_path.read_text(encoding="utf-8").split("\n\n[E2E Test]")[0]

    discourse.update_topic(url=topic_url, content=source, edit_reason="Revert E2E Tests")

    result = result and general_cleanup(repository)

    return result


if __name__ == "__main__":
    main()
