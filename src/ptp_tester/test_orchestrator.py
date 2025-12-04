"""Test Orchestrator for coordinating PTP testing workflow."""

import logging
import time
from datetime import datetime
from typing import List, Optional, Dict

from ptp_tester.aws_manager import AWSManager
from ptp_tester.ssh_manager import SSHManager
from ptp_tester.ptp_configurator import PTPConfigurator
from ptp_tester.models import (
    InstanceConfig,
    InstanceDetails,
    TestResult,
    PTPStatus
)


logger = logging.getLogger(__name__)


class TestOrchestrator:
    """Orchestrates the complete PTP testing workflow.
    
    This class coordinates:
    - AWS Manager for instance lifecycle
    - SSH Manager for remote connections
    - PTP Configurator for PTP setup and verification
    - Multi-instance testing with error resilience
    - Cleanup management based on test results
    """
    
    def __init__(
        self,
        aws_manager: AWSManager,
        ssh_manager: SSHManager,
        ptp_configurator: PTPConfigurator
    ):
        """Initialize Test Orchestrator with required components.
        
        Args:
            aws_manager: AWSManager instance for EC2 operations
            ssh_manager: SSHManager instance for SSH connections
            ptp_configurator: PTPConfigurator instance for PTP setup
        """
        self.aws_manager = aws_manager
        self.ssh_manager = ssh_manager
        self.ptp_configurator = ptp_configurator
    
    def test_instance_type(
        self,
        instance_type: str,
        subnet_id: str,
        key_name: str,
        ami_id: Optional[str] = None,
        security_group_ids: Optional[List[str]] = None,
        placement_group: Optional[str] = None,
        ssh_username: str = "ec2-user"
    ) -> TestResult:
        """Test PTP support on a single instance type.
        
        This method:
        1. Launches an EC2 instance
        2. Waits for it to reach running state
        3. Establishes SSH connection with retry logic
        4. Configures PTP on the instance
        5. Verifies PTP functionality
        6. Returns comprehensive test results
        
        Args:
            instance_type: EC2 instance type to test
            subnet_id: Subnet ID for instance launch
            key_name: EC2 key pair name
            ami_id: Optional AMI ID (uses latest AL2023 if not provided)
            security_group_ids: Optional security group IDs
            placement_group: Optional placement group name
            ssh_username: SSH username (default: ec2-user)
            
        Returns:
            TestResult with instance details, PTP status, and timing information
            
        Raises:
            Exception: If critical errors occur during testing
        """
        start_time = time.time()
        timestamp = datetime.now()
        
        logger.info(f"Starting PTP test for instance type: {instance_type}")
        
        instance_details = None
        ptp_status = None
        configuration_success = False
        connection = None
        
        try:
            # Step 1: Launch instance
            logger.info(f"Launching {instance_type} instance...")
            config = InstanceConfig(
                instance_type=instance_type,
                subnet_id=subnet_id,
                key_name=key_name,
                ami_id=ami_id,
                security_group_ids=security_group_ids,
                placement_group=placement_group
            )
            
            instance_details = self.aws_manager.launch_instance(config)
            logger.info(
                f"Instance launched: {instance_details.instance_id} "
                f"({instance_details.instance_type})"
            )
            
            # Step 2: Wait for instance to reach running state
            logger.info(f"Waiting for instance {instance_details.instance_id} to be running...")
            instance_details = self.aws_manager.wait_for_running(
                instance_details.instance_id,
                timeout=300
            )
            logger.info(f"Instance {instance_details.instance_id} is now running")
            
            # Determine which IP to use for SSH
            ssh_host = instance_details.public_ip or instance_details.private_ip
            if not ssh_host:
                raise RuntimeError(
                    f"Instance {instance_details.instance_id} has no accessible IP address"
                )
            
            logger.info(f"Will connect to instance via SSH at {ssh_host}")
            
            # Wait for SSH service to be ready
            logger.info("Waiting 10 seconds for SSH service to initialize...")
            time.sleep(10)
            
            # Step 3: Establish SSH connection with retry logic
            logger.info(f"Establishing SSH connection to {ssh_host}...")
            connection = self.ssh_manager.connect(
                host=ssh_host,
                username=ssh_username,
                max_retries=5,  # More retries for initial connection
                initial_backoff=10.0  # Wait longer initially for SSH to be ready
            )
            logger.info("SSH connection established successfully")
            
            # Step 4: Configure PTP
            logger.info("Starting PTP configuration...")
            configuration_success, connection = self._configure_ptp(
                connection,
                ssh_host,
                ssh_username
            )
            
            if not configuration_success:
                logger.warning("PTP configuration failed or incomplete")
            else:
                logger.info("PTP configuration completed successfully")
            
            # Step 5: Verify PTP functionality
            logger.info("Verifying PTP functionality...")
            ptp_status = self.ptp_configurator.verify_ptp(
                self.ssh_manager,
                connection
            )
            
            if ptp_status.supported:
                logger.info(
                    f"PTP is SUPPORTED on {instance_type} "
                    f"(clock device: {ptp_status.clock_device})"
                )
            else:
                logger.warning(
                    f"PTP is NOT SUPPORTED on {instance_type}: "
                    f"{ptp_status.error_message}"
                )
                
                # Run troubleshooting to identify configuration issues
                logger.info("Running troubleshooting diagnostics...")
                try:
                    troubleshooting_results = self.ptp_configurator.troubleshoot_ptp_issues(
                        self.ssh_manager,
                        connection
                    )
                    
                    # Add troubleshooting results to diagnostic output
                    if ptp_status.diagnostic_output is None:
                        ptp_status.diagnostic_output = {}
                    ptp_status.diagnostic_output['troubleshooting'] = troubleshooting_results
                    
                    # Log summary
                    summary = troubleshooting_results.get('summary', {})
                    logger.info(
                        f"Troubleshooting complete: {summary.get('passed', 0)}/{summary.get('total_checks', 0)} "
                        f"checks passed, {summary.get('issues_count', 0)} issues found"
                    )
                    
                    # Log recommendations
                    recommendations = troubleshooting_results.get('recommendations', [])
                    if recommendations:
                        logger.info(f"Recommendations: {len(recommendations)} suggestions available")
                        for i, rec in enumerate(recommendations[:3], 1):  # Log first 3
                            logger.info(f"  {i}. {rec}")
                        
                except Exception as e:
                    logger.warning(f"Troubleshooting failed: {e}")
            
        except Exception as e:
            logger.error(f"Test failed for {instance_type}: {e}")
            
            # Create a failed PTP status if we don't have one
            if ptp_status is None:
                ptp_status = PTPStatus(
                    supported=False,
                    error_message=f"Test failed: {str(e)}"
                )
            
            # If we don't have instance details, we can't continue
            if instance_details is None:
                raise
                
        finally:
            # Always disconnect SSH
            if connection:
                try:
                    self.ssh_manager.disconnect(connection)
                    logger.info("SSH connection closed")
                except Exception as e:
                    logger.warning(f"Error closing SSH connection: {e}")
        
        # Calculate test duration
        duration_seconds = time.time() - start_time
        
        # Create and return test result
        result = TestResult(
            instance_details=instance_details,
            ptp_status=ptp_status,
            configuration_success=configuration_success,
            timestamp=timestamp,
            duration_seconds=duration_seconds
        )
        
        logger.info(
            f"Test completed for {instance_type} in {duration_seconds:.1f}s "
            f"(PTP supported: {ptp_status.supported})"
        )
        
        return result
    
    def _configure_ptp(
        self,
        connection,
        ssh_host: str,
        ssh_username: str
    ) -> tuple:
        """Execute complete PTP configuration workflow.
        
        Args:
            connection: Active SSH connection
            ssh_host: Instance IP address for reconnection
            ssh_username: SSH username for reconnection
            
        Returns:
            Tuple of (success: bool, connection: SSHClient)
            Returns updated connection (may be reconnected)
        """
        try:
            # Detect the primary network interface
            interface = self.ptp_configurator.get_primary_network_interface(
                self.ssh_manager,
                connection
            )
            logger.info(f"Detected network interface: {interface}")
            
            # Check ENA driver version
            is_compatible, version = self.ptp_configurator.check_ena_driver_version(
                self.ssh_manager,
                connection
            )
            
            # If driver version is incompatible, try to upgrade
            if not is_compatible:
                logger.info(
                    f"ENA driver version {version} is below 2.10.0, "
                    "attempting upgrade..."
                )
                upgrade_success = self.ptp_configurator.upgrade_ena_driver(
                    self.ssh_manager,
                    connection
                )
                
                if not upgrade_success:
                    logger.error("ENA driver upgrade failed")
                    return (False, connection)
            
            # CRITICAL: Compile and install ENA driver with PHC support
            # The stock ENA driver on AL2023 does not have PHC support compiled in
            logger.info("Compiling ENA driver with PHC support enabled...")
            compile_success, needs_reconnect = self.ptp_configurator.compile_ena_driver_with_phc(
                self.ssh_manager,
                connection,
                ssh_host
            )
            
            # Handle reconnection if driver was reloaded
            if needs_reconnect:
                logger.info("Reconnecting SSH after driver reload...")
                try:
                    # Close old connection
                    self.ssh_manager.disconnect(connection)
                except Exception as e:
                    logger.debug(f"Error closing old connection (expected): {e}")
                
                # Reconnect with retries
                connection = self.ssh_manager.connect(
                    host=ssh_host,
                    username=ssh_username,
                    max_retries=5,
                    initial_backoff=5.0
                )
                logger.info("✓ SSH reconnected successfully after driver reload")
                
                # Retrieve and display driver reload diagnostics
                logger.info("Retrieving driver reload diagnostics...")
                reload_diagnostics = self.ptp_configurator.get_phc_reload_diagnostics(
                    self.ssh_manager,
                    connection
                )
                # Diagnostics are already logged by the method
                
                # CRITICAL: Verify PHC enablement after driver reload
                logger.info("Verifying PHC enablement after driver reload...")
                phc_success, phc_diagnostics = self.ptp_configurator.verify_phc_enablement_post_reload(
                    self.ssh_manager,
                    connection
                )
                
                if phc_success:
                    logger.info("✓ PHC enablement verified successfully!")
                    logger.info("  - PTP device created")
                    logger.info("  - ENA PTP clock registered")
                else:
                    logger.warning("⚠️  PHC enablement verification failed")
                    logger.warning("  Check the diagnostics above for details")
            
            if not compile_success:
                logger.warning(
                    "Failed to compile ENA driver with PHC support. "
                    "This may indicate build dependencies are missing or compilation failed."
                )
                # Continue anyway to gather diagnostics
                
                # Try one more reload as a last resort
                logger.info("Attempting final ENA driver reload...")
                reload_success = self.ptp_configurator.reload_ena_driver(
                    self.ssh_manager,
                    connection
                )
                
                if not reload_success:
                    logger.error(
                        f"No PTP hardware clock device found after ENA driver reload. "
                        f"This instance type may not support PTP hardware timestamping. "
                        f"PTP support requires both:\n"
                        f"1. ENA driver version >= 2.10.0 (current: {version})\n"
                        f"2. Instance type with PTP-capable hardware (Nitro-based instances)\n"
                        f"The instance type should support PTP, but the hardware "
                        f"clock device was not created. This may indicate:\n"
                        f"  - The instance type does not have PTP-capable hardware\n"
                        f"  - A kernel or driver configuration issue\n"
                        f"  - The instance needs to be stopped and started (not rebooted)"
                    )
                    return (False, connection)
            
            # Install PTP packages
            # AWS ENA PTP uses chrony directly with PHC, NOT ptp4l/phc2sys
            # Configuration steps:
            # 1. Create /dev/ptp_ena symlink for consistent device naming
            # 2. Configure chrony to use /dev/ptp_ena as refclock
            # 3. Restart chrony
            # 4. Verify chrony is using PHC0 as preferred source
            
            # Create /dev/ptp_ena symlink
            if not self.ptp_configurator.create_ptp_ena_symlink(
                self.ssh_manager,
                connection
            ):
                logger.warning("/dev/ptp_ena symlink creation failed, but continuing...")
            
            # Configure chrony to use PTP hardware clock
            if not self.ptp_configurator.configure_chrony(
                self.ssh_manager,
                connection
            ):
                logger.error("Failed to configure chrony")
                return (False, connection)
            
            # Give chrony a moment to stabilize and sync with PHC
            logger.info("Waiting for chrony to synchronize with PTP hardware clock...")
            time.sleep(5)
            
            return (True, connection)
            
        except Exception as e:
            logger.error(f"PTP configuration failed with exception: {e}")
            return (False, connection)
    
    def test_multiple_instances(
        self,
        instance_types: List,  # List[str] or List[InstanceTypeSpec]
        subnet_id: str,
        key_name: str,
        ami_id: Optional[str] = None,
        security_group_ids: Optional[List[str]] = None,
        placement_group: Optional[str] = None,
        ssh_username: str = "ec2-user",
        warn_threshold: int = 3
    ) -> List[TestResult]:
        """Test PTP support on multiple instance types sequentially with quantity support.
        
        This method:
        1. Handles both List[str] (backward compatible) and List[InstanceTypeSpec] (with quantities)
        2. Warns if more than warn_threshold instance types are provided
        3. Tests each instance sequentially, launching multiple instances per type if quantity > 1
        4. Continues testing even if individual tests fail (error resilience)
        5. Returns results for all tested instances
        
        Args:
            instance_types: List of EC2 instance types (str) or InstanceTypeSpec objects
            subnet_id: Subnet ID for instance launch
            key_name: EC2 key pair name
            ami_id: Optional AMI ID (uses latest AL2023 if not provided)
            security_group_ids: Optional security group IDs
            placement_group: Optional placement group name
            ssh_username: SSH username (default: ec2-user)
            warn_threshold: Warn if more than this many instance types (default: 3)
            
        Returns:
            List of TestResult objects, one per instance
        """
        from ptp_tester.models import InstanceTypeSpec
        
        # Convert to InstanceTypeSpec if needed (backward compatibility)
        specs = []
        for item in instance_types:
            if isinstance(item, str):
                specs.append(InstanceTypeSpec(instance_type=item, quantity=1))
            elif isinstance(item, InstanceTypeSpec):
                specs.append(item)
            else:
                raise TypeError(f"Expected str or InstanceTypeSpec, got {type(item)}")
        
        # Calculate total instances
        total_instances = sum(spec.quantity for spec in specs)
        
        logger.info(
            f"Starting multi-instance test for {len(specs)} instance type(s) "
            f"with {total_instances} total instance(s)"
        )
        
        # Warn if testing many instance types
        if len(specs) > warn_threshold:
            logger.warning(
                f"Testing {len(specs)} instance types. "
                f"This may take a significant amount of time and incur AWS costs. "
                f"Consider testing fewer instance types at once."
            )
        
        results = []
        
        # Test each instance type with its quantity
        spec_index = 0
        for spec in specs:
            spec_index += 1
            instance_type = spec.instance_type
            quantity = spec.quantity
            
            logger.info(
                f"Testing instance type {spec_index}/{len(specs)}: {instance_type} "
                f"(quantity: {quantity})"
            )
            
            # Launch and test each instance for this type
            for instance_num in range(1, quantity + 1):
                logger.info(
                    f"Testing {instance_type} instance {instance_num} of {quantity}"
                )
                
                try:
                    result = self.test_instance_type(
                        instance_type=instance_type,
                        subnet_id=subnet_id,
                        key_name=key_name,
                        ami_id=ami_id,
                        security_group_ids=security_group_ids,
                        placement_group=placement_group,
                        ssh_username=ssh_username
                    )
                    
                    results.append(result)
                    
                    logger.info(
                        f"Completed test for {instance_type} instance {instance_num}/{quantity} "
                        f"(PTP supported: {result.ptp_status.supported})"
                    )
                    
                except Exception as e:
                    logger.error(
                        f"Test failed for {instance_type} instance {instance_num}/{quantity}: {e}. "
                        f"Continuing with remaining instances..."
                    )
                    # Continue with next instance (error resilience)
                    continue
        
        logger.info(
            f"Multi-instance testing complete. "
            f"Successfully tested {len(results)}/{total_instances} instance(s)"
        )
        
        return results
    
    def handle_cleanup(
        self,
        results: List[TestResult],
        auto_terminate_unsupported: bool = True,
        prompt_for_selection: bool = True
    ) -> Dict[str, List[str]]:
        """Handle cleanup of instances based on test results.
        
        This method:
        1. Auto-terminates instances without PTP support (if enabled)
        2. Displays PTP-functional instances with details
        3. Prompts user to select which instances to keep (if enabled)
        4. Terminates unselected instances
        
        Args:
            results: List of TestResult objects from testing
            auto_terminate_unsupported: Auto-terminate instances without PTP (default: True)
            prompt_for_selection: Prompt user for instance selection (default: True)
            
        Returns:
            Dictionary with:
                - 'terminated': List of terminated instance IDs
                - 'kept': List of kept instance IDs
                - 'failed': List of instance IDs that failed to terminate
        """
        logger.info("Starting cleanup process...")
        
        terminated = []
        kept = []
        failed = []
        
        # Separate results into supported and unsupported
        unsupported_results = [r for r in results if not r.ptp_status.supported]
        supported_results = [r for r in results if r.ptp_status.supported]
        
        # Step 1: Auto-terminate unsupported instances
        if auto_terminate_unsupported and unsupported_results:
            logger.info(
                f"Auto-terminating {len(unsupported_results)} instances "
                "without PTP support..."
            )
            
            for result in unsupported_results:
                instance_id = result.instance_details.instance_id
                instance_type = result.instance_details.instance_type
                
                try:
                    logger.info(
                        f"Terminating {instance_type} instance {instance_id} "
                        "(PTP not supported)"
                    )
                    
                    success = self.aws_manager.terminate_instance(
                        instance_id,
                        verify=True
                    )
                    
                    if success:
                        terminated.append(instance_id)
                        logger.info(f"Successfully terminated {instance_id}")
                    else:
                        failed.append(instance_id)
                        logger.error(f"Failed to terminate {instance_id}")
                        
                except Exception as e:
                    logger.error(f"Error terminating {instance_id}: {e}")
                    failed.append(instance_id)
        
        # Step 2: Handle PTP-functional instances
        if supported_results:
            logger.info(
                f"\nFound {len(supported_results)} instance(s) with functional PTP:"
            )
            
            # Display details of PTP-functional instances
            for i, result in enumerate(supported_results, 1):
                details = result.instance_details
                ptp = result.ptp_status
                
                logger.info(
                    f"\n{i}. Instance Type: {details.instance_type}\n"
                    f"   Instance ID: {details.instance_id}\n"
                    f"   Availability Zone: {details.availability_zone}\n"
                    f"   Subnet ID: {details.subnet_id}\n"
                    f"   Clock Device: {ptp.clock_device}\n"
                    f"   Public IP: {details.public_ip or 'N/A'}\n"
                    f"   Private IP: {details.private_ip}"
                )
            
            # Step 3: Prompt for selection (if enabled)
            if prompt_for_selection:
                logger.info(
                    "\nPlease select which instances to keep. "
                    "Unselected instances will be terminated."
                )
                
                # In a real implementation, this would prompt the user
                # For now, we'll keep all PTP-functional instances by default
                # This will be implemented in the CLI layer
                
                # For this implementation, we'll keep all supported instances
                for result in supported_results:
                    kept.append(result.instance_details.instance_id)
                    logger.info(
                        f"Keeping instance {result.instance_details.instance_id} "
                        f"({result.instance_details.instance_type})"
                    )
            else:
                # If not prompting, keep all supported instances
                for result in supported_results:
                    kept.append(result.instance_details.instance_id)
        
        # Summary
        logger.info(
            f"\nCleanup complete:\n"
            f"  Terminated: {len(terminated)} instance(s)\n"
            f"  Kept: {len(kept)} instance(s)\n"
            f"  Failed: {len(failed)} instance(s)"
        )
        
        if failed:
            logger.warning(
                f"The following instances failed to terminate and may require "
                f"manual cleanup: {', '.join(failed)}"
            )
        
        return {
            'terminated': terminated,
            'kept': kept,
            'failed': failed
        }
