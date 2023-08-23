# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Functions that exit the e2e test process."""

import logging
import sys

from git import GitCommandError
from github import GithubException

from src.gatekeeper.constants import DOCUMENTATION_TAG
from src.gatekeeper.repository import DEFAULT_BRANCH_NAME, Client

E2E_SETUP = "origin/tests/e2e"
E2E_BASE = "tests/base"
E2E_BRANCH = "tests/feature"


def with_result(check_result: bool) -> None:
    """Exit and set exit code based on the check result.

    Args:
        check_result: The outcome of a check.
    """
    sys.exit(0 if check_result else 1)


def close_pull_request(repository: Client) -> None:
    """Close PR if it is open.

    Args:
        repository: RepositoryClient that is associated with the code
    """
    pull_request = repository.get_pull_request(DEFAULT_BRANCH_NAME)

    if pull_request:
        pull_request.edit(state="closed")
        repository._git_repo.git.push(  # pylint: disable=W0212
            "origin", "--delete", DEFAULT_BRANCH_NAME
        )


def general_cleanup(repository: Client) -> bool:
    """Perform general cleanup of open PR and branches.

    Args:
        repository: RepositoryClient that is associated with the code

    Returns:
        boolean representing whether the operation was successful
    """
    result = True

    # Delete the update tag
    try:
        tag_name = DOCUMENTATION_TAG
        update_tag = repository._github_repo.get_git_ref(  # pylint: disable=W0212
            f"tags/{tag_name}"
        )
        update_tag.delete()
    except GithubException as exc:
        logging.exception("cleanup failed for GitHub update tag, %s", exc)
        result = False

    close_pull_request(repository)

    repository._git_repo.git.fetch("--all")  # pylint: disable=W0212

    for branch in [DEFAULT_BRANCH_NAME, E2E_BASE, E2E_BRANCH]:
        if branch in repository.branches:
            if branch in repository.branches:
                try:
                    repository._git_repo.git.branch("-D", branch)  # pylint: disable=W0212
                except GitCommandError:
                    logging.info("Branch %s not found locally", branch)
                    result = False
            try:
                repository._git_repo.git.push(  # pylint: disable=W0212
                    "origin", "--delete", branch
                )
            except GitCommandError:
                logging.info("Branch %s not found in remote", branch)
                result = False

    return result
