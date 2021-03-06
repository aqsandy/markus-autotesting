import os
from typing import Tuple
from autotester.exceptions import TesterUserError
from autotester.config import config
from autotester.server.utils.string_management import decode_if_bytes


def tester_user() -> Tuple[str, str]:
    """
    Get the workspace for the tester user specified by the WORKERUSER
    environment variable, return the user_name and path to that user's workspace.

    Raises an AutotestError if a tester user is not specified or if a workspace
    has not been setup for that user.
    """
    user_name = os.environ.get("WORKERUSER")
    if user_name is None:
        raise TesterUserError("No worker users available to run this job")

    user_workspace = os.path.join(config["workspace"], config["_workspace_contents", "_workers"], user_name)
    if not os.path.isdir(user_workspace):
        raise TesterUserError(f"No workspace directory for user: {user_name}")

    return user_name, user_workspace


def get_reaper_username(test_username: str) -> str:
    """
    Return the name of the user designated as the reaper for test_username.
    A reaper user cleans up all remaining processes run by test_username.

    Returns None if there is no associated reaper user.
    """
    for users in (users for conf in config["workers"] for users in conf["users"]):
        if users["name"] == test_username:
            return users.get("reaper")
