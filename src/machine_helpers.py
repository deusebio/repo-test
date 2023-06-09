"""Machine Charm specific functions for operating MongoDB."""
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import os
import pwd
from pathlib import Path

from charms.mongodb.v0.helpers import get_mongod_args
from charms.mongodb.v0.mongodb import MongoDBConfiguration

logger = logging.getLogger(__name__)

ENV_VAR_PATH = "/etc/environment"
DB_PROCESS = "/usr/bin/mongod"
ROOT_USER_GID = 0
MONGO_USER = "snap_daemon"

MONGODB_SNAP_DATA_DIR = "/var/snap/charmed-mongodb/current"
MONGOD_CONF_DIR = f"{MONGODB_SNAP_DATA_DIR}/etc/mongod"
MONGOD_CONF_FILE_PATH = f"{MONGOD_CONF_DIR}/mongod.conf"


def update_mongod_service(auth: bool, machine_ip: str, config: MongoDBConfiguration) -> None:
    """Updates the mongod service file with the new options for starting."""
    with open(ENV_VAR_PATH, "r") as env_var_file:
        env_vars = env_var_file.readlines()

    # write our arguments and write them to /etc/environment - the environment variable here is
    # read in in the charmed-mongob.mongod.service file.
    mongod_start_args = get_mongod_args(config, auth, snap_install=True)
    args_added = False
    for index, line in enumerate(env_vars):
        if "MONGOD_ARGS" in line:
            args_added = True
            env_vars[index] = f"MONGOD_ARGS={mongod_start_args}"

    # if it is the first time adding these args to the file - will will need to append them to the
    # file
    if not args_added:
        env_vars.append(f"MONGOD_ARGS={mongod_start_args}")

    with open(ENV_VAR_PATH, "w") as service_file:
        service_file.writelines(env_vars)


def push_file_to_unit(parent_dir, file_name, file_contents) -> None:
    """K8s charms can push files to their containers easily, this is the vm charm workaround."""
    Path(parent_dir).mkdir(parents=True, exist_ok=True)
    file_name = f"{parent_dir}/{file_name}"
    with open(file_name, "w") as write_file:
        write_file.write(file_contents)

    # MongoDB limitation; it is needed 400 rights for keyfile and we need 440 rights on tls certs
    # to be able to connect via MongoDB shell
    if "keyFile" in file_name:
        os.chmod(file_name, 0o400)
    else:
        os.chmod(file_name, 0o440)
    mongodb_user = pwd.getpwnam(MONGO_USER)
    os.chown(file_name, mongodb_user.pw_uid, ROOT_USER_GID)


class ApplicationHostNotFoundError(Exception):
    """Raised when a queried host is not in the application peers or the current host."""
