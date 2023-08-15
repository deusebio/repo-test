#!/usr/bin/env python3
"""Charm code for MongoDB service."""
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import ops.charm
from ops.main import main
from ops.model import (
    ActiveStatus,
    MaintenanceStatus,
)

logger = logging.getLogger(__name__)


class DummyCharm(ops.charm.CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)

    def _on_install(self, event) -> None:
        """Handle the install event (fired on startup)."""
        self.unit.status = MaintenanceStatus("Installing")

    def _on_start(self, event: ops.charm.StartEvent) -> None:
        """Enables MongoDB service and initialises replica set.

        Args:
            event: The triggering start event.
        """
        self.unit.status = ActiveStatus("")

    def _on_update_status(self, event):
        logger.info("Update status fired.")


if __name__ == "__main__":
    main(DummyCharm)
