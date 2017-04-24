# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Base power driver."""

__all__ = [
    "is_power_parameter_set",
    "POWER_QUERY_TIMEOUT",
    "PowerActionError",
    "PowerAuthError",
    "PowerConnError",
    "PowerDriver",
    "PowerDriverBase",
    "PowerError",
    "PowerFatalError",
    "PowerSettingError",
    "PowerToolError",
    ]

from abc import (
    ABCMeta,
    abstractmethod,
    abstractproperty,
)
from datetime import timedelta
import sys

from jsonschema import validate
from provisioningserver.drivers import (
    JSON_SETTING_SCHEMA,
    validate_settings,
)
from provisioningserver.utils.registry import Registry
from provisioningserver.utils.twisted import pause
from twisted.internet import reactor
from twisted.internet.defer import (
    inlineCallbacks,
    returnValue,
)
from twisted.internet.threads import deferToThread

# A policy used when waiting between retries of power changes.
DEFAULT_WAITING_POLICY = (1, 2, 2, 4, 6, 8, 12)


JSON_POWER_DRIVERS_SCHEMA = {
    'title': "Power drivers parameters set",
    'type': 'array',
    'items': JSON_SETTING_SCHEMA,
}


# Timeout for the power query action. We might be holding up a thread for that
# long but some BMCs (notably seamicro) can take a long time to respond to
# a power query request.
# This should be configurable per-BMC.
POWER_QUERY_TIMEOUT = timedelta(seconds=45).total_seconds()


def is_power_parameter_set(param):
    return not (param is None or param == "" or param.isspace())


class PowerError(Exception):
    """Base error for all power driver failure commands."""


class PowerFatalError(PowerError):
    """Error that is raised when the power action should not continue to
    retry at all.

    This exception will cause the power action to fail instantly,
    without retrying.
    """


class PowerSettingError(PowerFatalError):
    """Error that is raised when the power type is missing argument
    that is required to control the BMC.

    This exception will cause the power action to fail instantly,
    without retrying.
    """


class PowerToolError(PowerFatalError):
    """Error that is raised when the power tool is missing completely
    for use.

    This exception will cause the power action to fail instantly,
    without retrying.
    """


class PowerAuthError(PowerFatalError):
    """Error raised when power driver fails to authenticate to BMC.

    This exception will cause the power action to fail instantly,
    without retrying.
    """


class PowerConnError(PowerError):
    """Error raised when power driver fails to communicate to BMC."""


class PowerActionError(PowerError):
    """Error when actually performing an action on the BMC, like `on`
    or `off`."""


class PowerDriverBase(metaclass=ABCMeta):
    """Base driver for a power driver."""

    def __init__(self):
        super(PowerDriverBase, self).__init__()
        validate_settings(self.get_schema())

    @abstractproperty
    def name(self):
        """Name of the power driver."""

    @abstractproperty
    def description(self):
        """Description of the power driver."""

    @abstractproperty
    def settings(self):
        """List of settings for the driver.

        Each setting in this list will be different per user. They are passed
        to the `on`, `off`, and `query` using the context. It is up
        to the driver to read these options before performing the operation.
        """

    @abstractmethod
    def on(self, system_id, context):
        """Perform the power on action for `system_id`.

        :param system_id: `Node.system_id`
        :param context: Power settings for the node.
        """

    @abstractmethod
    def off(self, system_id, context):
        """Perform the power off action for `system_id`.

        :param system_id: `Node.system_id`
        :param context: Power settings for the node.
        """

    @abstractmethod
    def cycle(self, system_id, context):
        """Perform the cycle action for `system_id`.

        :param system_id: `Node.system_id`
        :param context: Power settings for the node.
        """

    @abstractmethod
    def query(self, system_id, context):
        """Perform the query action for `system_id`.

        :param system_id: `Node.system_id`
        :param context: Power settings for the node.
        :return: status of power on BMC. `on` or `off`.
        :raises PowerError: states unable to get status from BMC. It is
            up to this method to report the actual issue to the Region. The
            calling function should ignore this error, and continue on.
        """

    def get_schema(self):
        """Returns the JSON schema for the driver."""
        return dict(
            name=self.name, description=self.description,
            fields=self.settings)


def get_error_message(err):
    """Returns the proper error message based on error."""
    if isinstance(err, PowerAuthError):
        return "Could not authenticate to node's BMC: %s" % err
    elif isinstance(err, PowerConnError):
        return "Could not contact node's BMC: %s" % err
    elif isinstance(err, PowerSettingError):
        return "Missing or invalid power setting: %s" % err
    elif isinstance(err, PowerToolError):
        return "Missing power tool: %s" % err
    elif isinstance(err, PowerActionError):
        return "Failed to complete power action: %s" % err
    else:
        return "Failed talking to node's BMC: %s" % err


class PowerDriver(PowerDriverBase):
    """Default power driver logic."""

    wait_time = DEFAULT_WAITING_POLICY

    def __init__(self, clock=reactor):
        self.clock = reactor

    @abstractmethod
    def detect_missing_packages(self):
        """Implement this method for the actual implementation
        of the check for the driver's missing support packages.
        """

    @abstractmethod
    def power_on(self, system_id, context):
        """Implement this method for the actual implementation
        of the power on command.
        """

    @abstractmethod
    def power_off(self, system_id, context):
        """Implement this method for the actual implementation
        of the power off command.
        """

    @abstractmethod
    def power_query(self, system_id, context):
        """Implement this method for the actual implementation
        of the power query command."""

    def on(self, system_id, context):
        """Performs the power on action for `system_id`.

        Do not override `on` method unless you want to provide custom logic on
        how retries and error detection is handled. Override `power_on` for
        just the power on action, and `on` will handle the retrying.
        """
        return self.perform_power(self.power_on, "on", system_id, context)

    def off(self, system_id, context):
        """Performs the power off action for `system_id`.

        Do not override `off` method unless you want to provide custom logic on
        how retries and error detection is handled. Override `power_off` for
        just the power off action, and `off` will handle the retrying and error
        reporting.
        """
        return self.perform_power(self.power_off, "off", system_id, context)

    @inlineCallbacks
    def cycle(self, system_id, context):
        """Performs the power cycle action for `system_id`.

        Do not override `cycle` method unless you want to provide custom logic
        on how retries and error detection is handled.
        """
        state = yield self.query(system_id, context)
        if state == 'on':
            yield self.perform_power(self.power_off, "off", system_id, context)
        yield self.perform_power(self.power_on, "on", system_id, context)

    @inlineCallbacks
    def query(self, system_id, context):
        """Performs the power query action for `system_id`."""
        exc_info = None, None, None
        for waiting_time in self.wait_time:
            try:
                state = yield deferToThread(
                    self.power_query, system_id, context)
            except PowerFatalError:
                raise  # Don't retry.
            except PowerError:
                exc_info = sys.exc_info()
                # Wait before retrying.
                yield pause(waiting_time, self.clock)
            else:
                returnValue(state)
        else:
            raise exc_info[0](exc_info[1]).with_traceback(exc_info[2])

    @inlineCallbacks
    def perform_power(self, power_func, state_desired, system_id, context):
        """Provides the logic to perform the power actions.

        :param power_func: Function used to change the power state of the
            node. Typically this will be `self.power_on` or `self.power_off`.
        :param state_desired: The desired state for this node to be in,
            typically "on" or "off".
        :param system_id: The node's system ID.
        """

        state = "unknown"
        exc_info = None, None, None

        for waiting_time in self.wait_time:
            # Try to change state.
            try:
                yield deferToThread(
                    power_func, system_id, context)
            except PowerFatalError:
                raise  # Don't retry.
            except PowerError:
                exc_info = sys.exc_info()
                # Wait before retrying.
                yield pause(waiting_time, self.clock)
            else:
                # Wait before checking state.
                yield pause(waiting_time, self.clock)
                # Try to get power state.
                try:
                    state = yield deferToThread(
                        self.power_query, system_id, context)
                except PowerFatalError:
                    raise  # Don't retry.
                except PowerError:
                    exc_info = sys.exc_info()
                else:
                    # If state is now the correct state, done.
                    if state == state_desired:
                        return

        if exc_info == (None, None, None):
            # No error found, so communication to the BMC is good, state must
            # have not changed in the elapsed time. That is the only reason we
            # should make it this far.
            raise PowerError(
                "Failed to power %s. BMC never transitioned from %s to %s."
                % (system_id, state, state_desired))
        else:
            # Report the last error.
            raise exc_info[0](exc_info[1]).with_traceback(exc_info[2])


class PowerDriverRegistry(Registry):
    """Registry for power drivers."""

    @classmethod
    def get_schema(cls):
        """Returns the full schema for the registry."""
        schemas = [drivers.get_schema() for _, drivers in cls]
        validate(schemas, JSON_POWER_DRIVERS_SCHEMA)
        return schemas


from provisioningserver.drivers.power.amt import AMTPowerDriver
from provisioningserver.drivers.power.apc import APCPowerDriver
from provisioningserver.drivers.power.dli import DLIPowerDriver
from provisioningserver.drivers.power.wedge import WedgePowerDriver
from provisioningserver.drivers.power.fence_cdu import FenceCDUPowerDriver
from provisioningserver.drivers.power.hmc import HMCPowerDriver
from provisioningserver.drivers.power.ipmi import IPMIPowerDriver
from provisioningserver.drivers.power.manual import ManualPowerDriver
from provisioningserver.drivers.power.msftocs import MicrosoftOCSPowerDriver
from provisioningserver.drivers.power.moonshot import MoonshotIPMIPowerDriver
from provisioningserver.drivers.power.mscm import MSCMPowerDriver
from provisioningserver.drivers.power.seamicro import SeaMicroPowerDriver
from provisioningserver.drivers.power.ucsm import UCSMPowerDriver
from provisioningserver.drivers.power.virsh import VirshPowerDriver
from provisioningserver.drivers.power.vmware import VMwarePowerDriver
from provisioningserver.drivers.power.nova import NovaPowerDriver
from provisioningserver.drivers.power.pipower import PIPowerPowerDriver

power_drivers = [
    AMTPowerDriver(),
    APCPowerDriver(),
    DLIPowerDriver(),
    WedgePowerDriver(),
    FenceCDUPowerDriver(),
    HMCPowerDriver(),
    IPMIPowerDriver(),
    ManualPowerDriver(),
    MicrosoftOCSPowerDriver(),
    MoonshotIPMIPowerDriver(),
    MSCMPowerDriver(),
    SeaMicroPowerDriver(),
    UCSMPowerDriver(),
    VirshPowerDriver(),
    VMwarePowerDriver(),
    NovaPowerDriver(),
    PIPowerPowerDriver(),
]
for driver in power_drivers:
    PowerDriverRegistry.register_item(driver.name, driver)

power_drivers_by_name = {
    d.name: d for d in power_drivers
}
