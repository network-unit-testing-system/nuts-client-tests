"""Connectivity test using ping from a Linux host."""
import pytest
import json
from typing import Dict, List, Callable, Any, Optional

from nornir.core.task import Task, Result
from nornir_netmiko import netmiko_send_command

from nuts.context import NornirNutsContext
from nuts.helpers.result import NutsResult
from nuts.helpers.errors import Error
from nuts.base_tests.napalm_ping import PingExtractor, Ping


class PingTaskError(Error):

    """Ping nornir task failed"""


class LinuxPingExtractor(PingExtractor):
    def _allowed_max_drop_for_destination(self, host: str, dest: str) -> int:
        """
        Matches the host-destination pair from a nornir task to the
        host-destination pair from test_data and retrieves its
        max_drop value that has been defined for that pair.

        :param host: host entry from the nornir task
        :param dest: destination that was pinged by a host from the nornir task
        :return: max_drop value from test_data
        """
        test_data: List[Dict[str, Any]] = self._nuts_ctx.nuts_parameters["test_data"]
        for entry in test_data:
            if entry["host"] == host and entry["destination"] == dest:
                return entry["max_drop"]
        return 0

    def _map_result_to_enum(
        self, result: Dict[str, Dict[Any, Any]], max_drop: int
    ) -> Ping:
        """
        Evaluates the ping that has been conducted with nornir and matches it
        to a Ping-Enum which can be either FAIL, SUCCESS or FLAPPING.

        FAIL: Packet loss equals probes sent.
        SUCCESS: Packet loss is below or equal max_drop.
        FLAPPING: Everything else.

        :param result: a single nornir Result
        :param max_drop: max_drop threshold
        :return: evaluated ping result
        """
        if result["packets_received"] == 0:
            return Ping.FAIL
        if result["packets_transmitted"] - result["packets_received"] <= max_drop:
            return Ping.SUCCESS
        else:
            return Ping.FLAPPING


class PingContext(NornirNutsContext):
    """
    - test_module: nuts_client_tests
      test_class: TestLinuxPing
      test_execution:
          ttl: <number, optional>
          timeout: <number, optional>
          size: <number, optional>
          count: <number, optional>
          source: <string, optional>
      test_data:
        - host: <host name, required>
          destination: <IP Address>
          expected: <SUCCESS|FAIL|FLAPPING>
          max_drop: <number>
    """

    id_format = "{host}_{destination}"

    def nuts_task(self) -> Callable[..., Result]:
        return self.ping_multi_dests

    def _generate_ping_command(
        self,
        destination: str,
        count: int = 5,
        ttl: Optional[int] = None,
        timeout: Optional[int] = None,
        size: Optional[int] = None,
        source: Optional[str] = None,
    ) -> str:
        ping_options = []

        if ttl:
            ping_options.append(f"-t {ttl}")
        if size:
            ping_options.append(f"-s {size}")
        if timeout:
            ping_options.append(f"-W {timeout}")
        if source:
            ping_options.append(f"-I {source}")

        return f"ping -n -c {count} {destination} {' '.join(ping_options)}  | jc --ping"

    def ping_multi_dests(self, task: Task, **kwargs: Any) -> Result:
        """
        One host pings all destinations as defined in the test bundle.

        Note: The destination is not included in the nornir result if the ping fails.
        Therefore we cannot know which destination was not reachable,
        so we must patch the destination onto the result object to know later which
        host-destination pair actually failed.

        :param task: nornir task for ping
        :param kwargs: arguments from the test bundle for the napalm ping task, such as
        count, ttl, timeout
        :return: all pinged destinations per host
        """

        destinations_per_hosts = [
            entry["destination"]
            for entry in self.nuts_parameters["test_data"]
            if entry["host"] == task.host.name
        ]

        for destination in destinations_per_hosts:
            result = task.run(
                task=netmiko_send_command,
                command_string=self._generate_ping_command(
                    destination=destination, **kwargs
                ),
            )
            result[0].destination = destination  # type: ignore[attr-defined]
            try:
                result[0].result = json.loads(result[0].result)
            except json.JSONDecodeError:
                result[0].failed = True

            if result.failed:
                raise PingTaskError(result[0].exception or result[0].result)

        return Result(host=task.host, result="All pings executed")

    def nuts_extractor(self) -> LinuxPingExtractor:
        return LinuxPingExtractor(self)


CONTEXT = PingContext


class TestLinuxPing:
    @pytest.mark.nuts("expected")
    def test_ping(self, single_result: NutsResult, expected: str) -> None:
        assert (
            expected == single_result.result.name
        ), f"Ping was expected to {expected} but was {single_result.result.name}"
