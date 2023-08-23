# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Utility for running the reconcile action, primarily for testing purposes."""

import argparse
import contextlib
import json
import logging
import pathlib
from enum import Enum

from github.GithubException import UnknownObjectException
from github.Repository import Repository

from src.gatekeeper.constants import DOCUMENTATION_TAG
from src.gatekeeper.discourse import Discourse, create_discourse
from src.gatekeeper.exceptions import DiscourseError
from src.gatekeeper.repository import DEFAULT_BRANCH_NAME
from src.gatekeeper.repository import Client as RepositoryClient
from src.gatekeeper.repository import create_repository_client

from .common import E2E_BASE, E2E_SETUP, close_pull_request, general_cleanup, with_result


class Action(str, Enum):
    """The actions the utility can take.

    Attrs:
        CHECK_DRAFT: Check that the draft e2e test succeeded.
        CHECK_CREATE: Check that the create e2e test succeeded.
        CHECK_UPDATE: Check that the update e2e test succeeded.
        CHECK_DELETE_TOPICS: Check that the delete_topics e2e test succeeded.
        CHECK_DELETE: Check that the delete e2e test succeeded.
        CLEANUP: Discourse cleanup after the testing.
        PREPARE: Preparation steps for setting the stage for the integration tests
    """

    CHECK_DRAFT = "check-draft"
    CHECK_CREATE = "check-create"
    CHECK_UPDATE = "check-update"
    CHECK_DELETE_TOPICS = "check-delete-topics"
    CHECK_DELETE = "check-delete"
    CLEANUP = "cleanup"
    PREPARE = "prepare"


def main() -> None:
    """Execute requested reconcilliation action.

    Raises:
        NotImplementedError: if an action was received for which there is no imlpementation.
    """
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(
        prog="ReconcileTestSupport",
        description="Check or delete posts created on discourse during an action execution.",
    )
    parser.add_argument("urls_with_actions", help="The pages that were created during execution")
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
    urls_with_actions = json.loads(args.urls_with_actions)
    discourse_config = json.loads(args.discourse_config)
    action_kwargs = json.loads(args.action_kwargs)

    discourse = create_discourse(**discourse_config)
    repository = create_repository_client(args.github_token, pathlib.Path.cwd())

    match args.action:
        case Action.PREPARE.value:
            with_result(_prepare(repository, discourse))
        case Action.CHECK_DRAFT.value:
            with_result(check_draft(urls_with_actions=urls_with_actions, **action_kwargs))
        case Action.CHECK_CREATE.value:
            with_result(
                check_create(
                    repository=repository,
                    discourse=discourse,
                    urls_with_actions=urls_with_actions,
                    **action_kwargs,
                )
            )
        case Action.CHECK_UPDATE.value:
            with_result(
                check_update(
                    repository=repository,
                    discourse=discourse,
                    urls_with_actions=urls_with_actions,
                    **action_kwargs,
                )
            )
        case Action.CHECK_DELETE_TOPICS.value:
            with_result(
                check_delete_topics(
                    urls_with_actions=urls_with_actions, discourse=discourse, **action_kwargs
                )
            )
        case Action.CHECK_DELETE.value:
            with_result(
                check_delete(
                    urls_with_actions=urls_with_actions, discourse=discourse, **action_kwargs
                )
            )
        case Action.CLEANUP.value:
            with_result(
                cleanup(
                    repository=repository, discourse=discourse, urls_with_actions=urls_with_actions
                )
            )
        case _:
            raise NotImplementedError(f"{args.action} has not been implemented")


def _prepare(repository: RepositoryClient, discourse: Discourse) -> bool:  # pylint: disable=W0613
    """Prepare the stage for the tests.

    Args:
        repository: Client repository to used
        discourse: Discourse client class

    Returns:
        boolean representing whether the preparation was successful.
    """
    repository._git_repo.git.fetch("--all")  # pylint: disable=W0212

    repository.create_branch(E2E_BASE, E2E_SETUP).switch(E2E_BASE)

    repository._git_repo.git.push("-f", "origin", E2E_BASE)  # pylint: disable=W0212

    repository.tag_commit(DOCUMENTATION_TAG, repository.current_commit)

    repository.update_branch("First commit of documentation", force=True, directory=None)

    print(repository.current_commit)

    close_pull_request(repository)

    return True


def _check_url_count(
    urls_with_actions: dict[str, str], expected_count: int, test_name: str
) -> bool:
    """Perform the check for the number of URLs.

    Success is if the number of urls in urls_with_actions matches the expected count.

    Args:
        urls_with_actions: The URLs that had any actions against them.
        expected_count: The expected number of URLs.
        test_name: The name of the test to include in the logging message.

    Returns:
        Whether the test succeeded.
    """
    if (url_count := len(urls_with_actions)) != expected_count:
        logging.error(
            "%s check failed, expected %s URLs with actions, got %s, urls_with_actions=%s",
            test_name,
            expected_count,
            url_count,
            urls_with_actions,
        )
        return False
    return True


def _check_url_retrieve(
    urls_with_actions: dict[str, str], discourse: Discourse, test_name: str
) -> bool:
    """Check that retrieving the URL succeeds.

    Args:
        urls_with_actions: The URLs that had any actions against them.
        discourse: Client to the documentation server.
        test_name: The name of the test to include in the logging message.

    Returns:
        Whether the test succeeded.
    """
    for url in urls_with_actions.keys():
        try:
            discourse.retrieve_topic(url=url)
        except DiscourseError as exc:
            logging.error(
                "%s check failed, URL retrieval failed for %s, error: %s, urls_with_actions=%s",
                test_name,
                url,
                exc,
                urls_with_actions,
            )
            return False
    return True


def _check_url_result(
    urls_with_actions: dict[str, str], expected_result: list[str], test_name: str
) -> bool:
    """Check the results for the URLs.

    Args:
        urls_with_actions: The URLs that had any actions against them.
        expected_result: The expected results.
        test_name: The name of the test to include in the logging message.

    Returns:
        Whether the test succeeded.
    """
    if sorted(results := urls_with_actions.values()) != sorted(expected_result):
        logging.error(
            "%s check failed, the result is not as expected, "
            "got: %s, expected: %s, urls_with_actions=%s",
            test_name,
            results,
            expected_result,
            urls_with_actions,
        )
        return False
    return True


def _check_git_tag_exists(test_name: str, github_repo: Repository) -> bool:
    """Check that the content tag exists.

    Args:
        github_repo: The client to the GitHub repository.
        test_name: The name of the test to include in the logging message.

    Returns:
        Whether the test succeeded.
    """
    tag_name = DOCUMENTATION_TAG

    try:
        github_repo.get_git_ref(f"tags/{tag_name}")
    except UnknownObjectException:
        logging.error("%s check failed for tag %s, the tag does not exist", test_name, tag_name)
        return False
    return True


def check_draft(urls_with_actions: dict[str, str], expected_url_results: list[str]) -> bool:
    """Check that the draft test succeeded.

    Success is indicated by that there are the expected number of URLs in urls_with_actions.

    Args:
        urls_with_actions: The URLs that had any actions against them.
        expected_url_results: The expected url results.

    Returns:
        Whether the test succeeded.
    """
    test_name = "draft"
    if not _check_url_count(
        urls_with_actions=urls_with_actions,
        expected_count=len(expected_url_results),
        test_name=test_name,
    ):
        return False

    logging.info("%s check succeeded", test_name)
    return True


def check_create(
    repository: RepositoryClient,
    discourse: Discourse,
    urls_with_actions: dict[str, str],
    expected_url_results: list[str],
) -> bool:
    """Check that the create test succeeded.

    Success is indicated by that there are the expected number of URLs with the expected result and
    that retrieving the URLs succeeds.

    Args:
        repository: Github Repository client
        discourse: Client to the documentation server.
        urls_with_actions: The URLs that had any actions against them.
        expected_url_results: The expected url results.

    Returns:
        Whether the test succeeded.
    """
    test_name = "create"
    if not _check_url_count(
        urls_with_actions=urls_with_actions,
        expected_count=len(expected_url_results),
        test_name=test_name,
    ):
        return False

    if not _check_url_result(
        urls_with_actions=urls_with_actions,
        expected_result=expected_url_results,
        test_name=test_name,
    ):
        return False

    if not _check_url_retrieve(
        urls_with_actions=urls_with_actions, discourse=discourse, test_name=test_name
    ):
        return False

    with repository.with_branch(E2E_BASE) as repo:
        if not repo.tag_exists(DOCUMENTATION_TAG) == repo.current_commit:
            logging.error(
                "Failing tag existence check: %s != %s",
                repo.tag_exists(DOCUMENTATION_TAG),
                repo.current_commit,
            )
            return False

    logging.info("%s check succeeded", test_name)

    return True


def check_update(
    repository: RepositoryClient,
    discourse: Discourse,
    urls_with_actions: dict[str, str],
    expected_url_results: list[str],
) -> bool:
    """Check that the update test succeeded.

    Success is indicated by that there are the expected number of URLs with the expected result and
    that retrieving the URLs succeeds.

    Args:
        repository: Github Repository client
        discourse: Client to the documentation server.
        urls_with_actions: The URLs that had any actions against them.
        expected_url_results: The expected url results.

    Returns:
        Whether the test succeeded.
    """
    test_name = "update"
    if not _check_url_count(
        urls_with_actions=urls_with_actions,
        expected_count=len(expected_url_results),
        test_name=test_name,
    ):
        return False

    if not _check_url_result(
        urls_with_actions=urls_with_actions,
        expected_result=expected_url_results,
        test_name=test_name,
    ):
        return False

    if not _check_url_retrieve(
        urls_with_actions=urls_with_actions, discourse=discourse, test_name=test_name
    ):
        return False

    if not _check_git_tag_exists(
        test_name=test_name, github_repo=repository._github_repo  # pylint: disable=W0212
    ):
        return False

    if repository.get_pull_request(DEFAULT_BRANCH_NAME) is None:
        return False

    logging.info("%s check succeeded", test_name)

    repository._git_repo.git.fetch("--all")  # pylint: disable=W0212

    # If update was successful and a PR was created, we simulate the merge remotely
    repository.switch(E2E_SETUP)

    repository.create_branch(E2E_BASE, f"origin/{DEFAULT_BRANCH_NAME}").switch(E2E_BASE)
    repository._git_repo.git.push(  # pylint: disable=W0212
        "--set-upstream", "-f", "origin", E2E_BASE
    )  # pylint: disable=W0212

    return True


def check_delete_topics(
    urls_with_actions: dict[str, str], discourse: Discourse, expected_url_results: list[str]
) -> bool:
    """Check that the delete_topics test succeeded.

    Success is indicated by that there are the expected number of URLs and results in
    urls_with_actions and that retrieving the URLs succeeds (none have been deleted).

    Args:
        urls_with_actions: The URLs that had any actions against them.
        discourse: Client to the documentation server.
        expected_url_results: The expected url results.

    Returns:
        Whether the test succeeded.
    """
    test_name = "delete_topics"
    if not _check_url_count(
        urls_with_actions=urls_with_actions,
        expected_count=len(expected_url_results),
        test_name=test_name,
    ):
        return False

    if not _check_url_result(
        urls_with_actions=urls_with_actions,
        expected_result=expected_url_results,
        test_name=test_name,
    ):
        return False

    if not _check_url_retrieve(
        urls_with_actions=urls_with_actions, discourse=discourse, test_name=test_name
    ):
        return False

    logging.info("%s check succeeded", test_name)
    return True


def check_delete(
    urls_with_actions: dict[str, str], discourse: Discourse, expected_url_results: list[str]
) -> bool:
    """Check that the delete test succeeded.

    Success is indicated by that there are the expected number of URLs in urls_with_actions with a
    success result and that retrieving the first URL fails and the second succeeds.

    Args:
        urls_with_actions: The URLs that had any actions against them.
        discourse: Client to the documentation server.
        expected_url_results: The expected url results.

    Returns:
        Whether the test succeeded.
    """
    test_name = "delete"
    if not _check_url_count(
        urls_with_actions=urls_with_actions,
        expected_count=len(expected_url_results),
        test_name=test_name,
    ):
        return False

    if not _check_url_result(
        urls_with_actions=urls_with_actions,
        expected_result=expected_url_results,
        test_name=test_name,
    ):
        return False

    urls = tuple(urls_with_actions.keys())
    if not _check_url_retrieve(
        urls_with_actions={urls[1]: urls_with_actions[urls[1]]},
        discourse=discourse,
        test_name=test_name,
    ):
        return False

    with contextlib.suppress(DiscourseError):
        discourse.retrieve_topic(url=urls[0])
        logging.error(
            "%s check failed, topic not deleted, url: %s, urls_with_actions=%s",
            test_name,
            urls[0],
            urls_with_actions,
        )
        return False

    logging.info("%s check succeeded", test_name)
    return True


def cleanup(  # noqa: C901
    repository: RepositoryClient,
    discourse: Discourse,
    urls_with_actions: dict[str, str],
) -> bool:
    """Delete all URLs.

    Args:
        repository: Github Repository client
        discourse: Client to the documentation server.
        urls_with_actions: The URLs that had any actions against them.

    Returns:
        Whether the cleanup succeeded.
    """
    result = True

    # Delete topics from discourse
    for url in urls_with_actions.keys():
        try:
            discourse.delete_topic(url=url)
        except DiscourseError as exc:
            logging.exception("cleanup failed for discourse, %s", exc)
            result = False

    result = result and general_cleanup(repository)

    return result


if __name__ == "__main__":
    main()
