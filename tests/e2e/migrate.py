# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Utility for running the migration action, primarily for testing purposes."""

import argparse
import json
import logging
import sys
from enum import Enum
from pathlib import Path

from src.gatekeeper.constants import DOCUMENTATION_TAG
from src.gatekeeper.discourse import create_discourse, Discourse
from src.gatekeeper.repository import (
    Client,
    ACTIONS_PULL_REQUEST_TITLE,
    DEFAULT_BRANCH_NAME,
    create_repository_client,
)
from tests.e2e import exit_

E2E_SETUP = "origin/tests/e2e"
E2E_BASE = "tests/base"
E2E_BRANCH = "tests/feature"


class Action(str, Enum):
    """The actions the utility can take.

    Attrs:
        PREPARE: Prepare discourse pages before running the migration.
        CHECK_BRANCH: Check that the migration branch was created.
        CHECK_PULL_REQUEST: Check that the migration pull request was created.
        CLEANUP: Delete discourse pages and migration pull request and branch after the migration.
    """

    PREPARE = "prepare"
    CHECK_PULL_REQUEST = "check-pull-request"
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
    parser.add_argument(
        "--action-kwargs", help="Arguments for the action as a JSON mapping", default="{}"
    )
    parser.add_argument("--github-token", help="Github token to setup repository")
    args = parser.parse_args()
    discourse_config = json.loads(args.discourse_config)
    action_kwargs = json.loads(args.action_kwargs)

    discourse = create_discourse(**discourse_config)
    repository = create_repository_client(args.github_token, Path.cwd())

    match args.action:
        case Action.PREPARE.value:
            prepare(repository, discourse)
            sys.exit(0)
        case Action.CHECK_PULL_REQUEST.value:
            exit_.with_result(check_pull_request(repository, discourse))
        case Action.CLEANUP.value:
            exit_.with_result(cleanup(repository, discourse))
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

    repository._git_repo.git.push("-f", "origin", E2E_BASE)

    pull_request = repository.get_pull_request(DEFAULT_BRANCH_NAME)

    if pull_request:
        pull_request.edit(state="closed")
        repository._git_repo.git.push("origin", "--delete", DEFAULT_BRANCH_NAME)

    if repository.tag_exists(DOCUMENTATION_TAG):
        logging.info("Removing tag %s", DOCUMENTATION_TAG)
        repository._git_repo.git.tag("-d", DOCUMENTATION_TAG)  # pylint: disable=W0212
        repository._git_repo.git.push(  # pylint: disable=W0212
            "--delete", "origin", DOCUMENTATION_TAG
        )

    return True


def check_pull_request(repository: Client, discourse: Discourse) -> bool:
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


def cleanup(
        repository: Client, discourse: Discourse
) -> bool:
    """Clean up testing artifacts on GitHub and Discourse.

    Args:
        topics: The discourse topics created for the migration.
        github_access_token: The secret required for interactions with GitHub.
        discourse_config: Details required to communicate with discourse.

    Returns:
        Whether the cleanup succeeded.
    """
    result = True

    return result


if __name__ == "__main__":
    main()
