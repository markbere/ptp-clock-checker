"""PTP Instance Tester - A tool to test PTP hardware clock support on AWS EC2 instances."""

__version__ = "0.1.0"

from ptp_tester.aws_manager import AWSManager
from ptp_tester.ssh_manager import SSHManager
from ptp_tester.ptp_configurator import PTPConfigurator
from ptp_tester.test_orchestrator import TestOrchestrator
from ptp_tester.models import (
    InstanceConfig,
    InstanceDetails,
    CommandResult,
    PTPStatus,
    TestResult
)

__all__ = [
    'AWSManager',
    'SSHManager',
    'PTPConfigurator',
    'TestOrchestrator',
    'InstanceConfig',
    'InstanceDetails',
    'CommandResult',
    'PTPStatus',
    'TestResult',
]
