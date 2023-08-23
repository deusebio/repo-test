#!/usr/bin/env python3
"""Charm code for MongoDB service."""
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from typing import Any

import ops.charm
from ops import EventBase
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus

logger = logging.getLogger(__name__)


class DummyCharm(ops.charm.CharmBase):
    """Charm the service."""

    def __init__(self, *args: Any):
        """Instantiate a new basic dummy charm.

        Args:
            args: variable positional arguments
        """
        super().__init__(*args)

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)

    def _on_install(self, event: EventBase) -> None:  # pylint: disable=W0613
        """Handle the install event (fired on startup).

        Args:
            event: The triggering install event.
        """
        self.unit.status = MaintenanceStatus("Installing")

    def _on_start(self, event: EventBase) -> None:  # pylint: disable=W0613
        """Enable MongoDB service and initialises replica set.

        Args:
            event: The triggering start event.
        """
        self.unit.status = ActiveStatus("")

    def _on_update_status(self, event: EventBase) -> None:  # pylint: disable=W0613
        """Handle the update status event.

        Args:
            event: Update status event
        """
        logger.info("Update status fired.")


if __name__ == "__main__":
    main(DummyCharm)
