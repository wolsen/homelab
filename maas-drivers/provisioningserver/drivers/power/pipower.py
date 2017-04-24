# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""PIMI (raspberry pi based) Power Driver."""

__all__ = []

import json
import requests

from provisioningserver.drivers.power import (
    PowerAuthError,
    PowerDriver,
    PowerError,
    PowerFatalError,
    PowerToolError,
)
from provisioningserver.logger import get_maas_logger


maaslog = get_maas_logger("drivers.power.pipower")

HEADERS = {'Content-Type': 'application/json'}

OFF = 'off'
ON = 'on'


class PIPowerPowerDriver(PowerDriver):
    name = 'pipower'
    description = 'Raspberry Pi Power Driver'
    settings = []

    def detect_missing_packages(self):
        """Detects any missing packages required"""
        return []

    def _get_url(self, uri, name):
        if uri.endswith('/'):
            return '%s%s' % (uri, name)
        else:
            return '%s/%s' % (uri, name)

    def _do_power_control(self, action, name, uri, **kwargs):
        data = {'action': action}
        url = self._get_url(uri, name)

        response = requests.put(url, data=json.dumps(data), headers=HEADERS)
        if not response.ok:
            raise PowerError(response.text)

    def power_on(self, system_id, context):
        self._do_power_control(ON, **context)

    def power_off(self, system_id, context):
        self._do_power_control(OFF, **context)

    def power_query(self, system_id, context):
        uri = context['uri']
        name = context['name']
        url = self._get_url(uri, name)

        response = requests.get(url)
        if response.ok:
            return response.json()['power_state']

        raise PowerError(response.text)

