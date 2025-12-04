"""PTP Configurator for setting up and verifying PTP on EC2 instances."""

import logging
import re
import time
from typing import Tuple, Optional
from paramiko import SSHClient

from ptp_tester.ssh_manager import SSHManager
from ptp_tester.models import PTPStatus, CommandResult


logger = logging.getLogger(__name__)


class PTPConfigurator:
    """Handles PTP configuration and verification on EC2 instances.
    
    This class encapsulates all PTP-related operations including:
    - ENA driver version checking and upgrading
    - PTP package installation
    - Hardware timestamping enablement
    - PTP daemon configuration (ptp4l, phc2sys, chrony)
    - PTP functionality verification
    """
    
    # Minimum required ENA driver version for PTP support
    MIN_ENA_VERSION = (2, 10, 0)
    
    def __init__(self):
        """Initialize PTP Configurator."""
        pass
    
    def detect_architecture(
        self,
        ssh_manager: SSHManager,
        connection: SSHClient
    ) -> str:
        """Detect CPU architecture of the instance.
        
        Executes 'uname -m' to determine the CPU architecture.
        This is used to select appropriate AMIs and handle architecture-specific
        configurations.
        
        Args:
            ssh_manager: SSHManager instance for command execution
            connection: Active SSH connection to the instance
            
        Returns:
            Architecture string:
            - 'x86_64' for Intel/AMD processors
            - 'aarch64' for ARM64/Graviton processors
            - 'unknown' if detection fails
        """
        logger.info("Detecting instance CPU architecture...")
        
        try:
            result = ssh_manager.execute_command(
                connection,
                "uname -m",
                timeout=30
            )
            
            if not result.success:
                logger.warning(
                    f"Failed to detect architecture: {result.stderr}. "
                    "Defaulting to 'unknown'"
                )
                return "unknown"
            
            architecture = result.stdout.strip()
            
            if not architecture:
                logger.warning("Architecture detection returned empty string")
                return "unknown"
            
            logger.info(f"Detected CPU architecture: {architecture}")
            
            # Normalize architecture names
            if architecture in ['x86_64', 'amd64']:
                return 'x86_64'
            elif architecture in ['aarch64', 'arm64']:
                return 'aarch64'
            else:
                logger.warning(f"Unknown architecture: {architecture}")
                return architecture
                
        except Exception as e:
            logger.error(f"Architecture detection failed with exception: {e}")
            return "unknown"
    
    def get_primary_network_interface(
        self,
        ssh_manager: SSHManager,
        connection: SSHClient
    ) -> str:
        """Detect the primary ENA network interface name.
        
        EC2 instances use predictable network interface names like 'enp27s0'
        instead of the traditional 'eth0'. This method detects the actual
        interface name being used.
        
        Args:
            ssh_manager: SSHManager instance for command execution
            connection: Active SSH connection to the instance
            
        Returns:
            Interface name (e.g., 'enp27s0', 'eth0')
        """
        # Try to find ENA interface using predictable naming pattern
        result = ssh_manager.execute_command(
            connection,
            "ip -o link show | grep -E 'enp[0-9]+s[0-9]+' | head -1 | awk '{print $2}' | tr -d ':'",
            timeout=30
        )
        
        if result.success and result.stdout.strip():
            interface = result.stdout.strip()
            logger.info(f"Detected primary network interface: {interface}")
            return interface
        
        # Fallback: try to find any UP interface (excluding loopback)
        result = ssh_manager.execute_command(
            connection,
            "ip -o link show up | grep -v 'lo:' | head -1 | awk '{print $2}' | tr -d ':'",
            timeout=30
        )
        
        if result.success and result.stdout.strip():
            interface = result.stdout.strip()
            logger.info(f"Detected network interface (fallback): {interface}")
            return interface
        
        # Last resort fallback to eth0 for very old systems
        logger.warning("Could not detect network interface, falling back to eth0")
        return "eth0"
    
    def check_ena_driver_version(
        self,
        ssh_manager: SSHManager,
        connection: SSHClient
    ) -> Tuple[bool, str]:
        """Check if ENA driver version meets minimum requirements for PTP.
        
        Executes 'modinfo ena' to get the current driver version and compares
        it with the minimum required version (2.10.0).
        
        Args:
            ssh_manager: SSHManager instance for command execution
            connection: Active SSH connection to the instance
            
        Returns:
            Tuple of (is_compatible, version_string)
            - is_compatible: True if version >= 2.10.0, False otherwise
            - version_string: The detected version string (e.g., "2.10.0")
            
        Raises:
            Exception: If unable to determine driver version
        """
        logger.info("Checking ENA driver version...")
        
        # Get driver version using modinfo
        result = ssh_manager.execute_command(
            connection,
            "modinfo ena | grep '^version:' | awk '{print $2}'"
        )
        
        if not result.success:
            error_msg = f"Failed to get ENA driver version: {result.stderr}"
            logger.error(error_msg)
            raise Exception(error_msg)
        
        version_string = result.stdout.strip()
        
        if not version_string:
            error_msg = "Could not parse ENA driver version from modinfo output"
            logger.error(error_msg)
            raise Exception(error_msg)
        
        logger.info(f"Detected ENA driver version: {version_string}")
        
        # Parse version string (format: "2.10.0" or "2.10.0g" etc.)
        is_compatible = self._compare_version(version_string, self.MIN_ENA_VERSION)
        
        if is_compatible:
            logger.info(f"ENA driver version {version_string} is compatible (>= 2.10.0)")
        else:
            logger.warning(
                f"ENA driver version {version_string} is below minimum "
                f"required version 2.10.0"
            )
        
        return is_compatible, version_string
    
    def _compare_version(self, version_string: str, min_version: Tuple[int, int, int]) -> bool:
        """Compare version string with minimum required version.
        
        Args:
            version_string: Version string like "2.10.0" or "2.10.0g"
            min_version: Tuple of (major, minor, patch) integers
            
        Returns:
            True if version_string >= min_version, False otherwise
        """
        # Extract numeric version components using regex
        # Handles formats like "2.10.0", "2.10.0g", "2.10.0-beta", etc.
        match = re.match(r'^(\d+)\.(\d+)\.(\d+)', version_string)
        
        if not match:
            logger.warning(f"Could not parse version string: {version_string}")
            return False
        
        major, minor, patch = map(int, match.groups())
        current_version = (major, minor, patch)
        
        return current_version >= min_version
    
    def reload_ena_driver(
        self,
        ssh_manager: SSHManager,
        connection: SSHClient
    ) -> bool:
        """Reload the ENA driver module to trigger PTP device creation.
        
        This method unloads and reloads the ENA driver, which should create
        the /dev/ptp* device if the hardware supports PTP.
        
        Args:
            ssh_manager: SSHManager instance for command execution
            connection: Active SSH connection to the instance
            
        Returns:
            True if reload successful and PTP device created, False otherwise
        """
        logger.info("Reloading ENA driver to trigger PTP device creation...")
        
        try:
            # Reload the driver module
            result = ssh_manager.execute_command(
                connection,
                "sudo rmmod ena && sudo modprobe ena",
                timeout=30
            )
            
            if not result.success:
                logger.error(f"Failed to reload ENA driver: {result.stderr}")
                return False
            
            logger.info("ENA driver reloaded successfully")
            
            # Wait a moment for device creation
            time.sleep(2)
            
            # Check if ENA PTP device was created via sysfs
            result = ssh_manager.execute_command(
                connection,
                "for file in /sys/class/ptp/*/clock_name; do cat \"$file\" 2>/dev/null; done 2>/dev/null",
                timeout=30
            )
            
            if "ena-ptp" in result.stdout:
                logger.info(f"ENA PTP device created after driver reload: {result.stdout.strip()}")
                return True
            else:
                logger.warning(
                    "ENA driver reloaded but no ENA PTP device created. "
                    "This instance type may not have PTP-capable hardware."
                )
                return False
                
        except Exception as e:
            logger.error(f"ENA driver reload failed: {e}")
            return False
    
    def enable_ena_phc(
        self,
        ssh_manager: SSHManager,
        connection: SSHClient,
        instance_ip: str
    ) -> tuple[bool, bool]:
        """Enable PTP Hardware Clock (PHC) support on the ENA driver.
        
        PHC is disabled by default on the ENA driver. This method enables it using
        one of two approaches:
        1. devlink (preferred, Linux 6.16+)
        2. Module parameter (fallback for older kernels)
        
        According to ENA driver documentation:
        - PHC must be explicitly enabled
        - PTP module must be loaded first
        - Driver reload required after enabling
        
        IMPORTANT: Module parameter approach (rmmod/modprobe) will drop SSH connection!
        Caller must handle reconnection when needs_reconnect=True.
        
        Args:
            ssh_manager: SSHManager instance for command execution
            connection: Active SSH connection to the instance
            instance_ip: Instance IP address for reconnection
            
        Returns:
            Tuple of (success: bool, needs_reconnect: bool)
            - success: True if PHC enabled successfully
            - needs_reconnect: True if SSH connection was dropped and needs reconnection
        """
        logger.info("=" * 80)
        logger.info("STARTING PHC ENABLEMENT PROCESS - ENHANCED DIAGNOSTICS")
        logger.info("=" * 80)
        
        try:
            # PRE-CHECK: Capture baseline state before any changes
            logger.info("\n[PRE-CHECK] Capturing baseline state before PHC enablement...")
            
            # Check current PTP devices
            result = ssh_manager.execute_command(
                connection,
                "ls -la /dev/ptp* 2>&1; echo '---'; for f in /sys/class/ptp/*/clock_name; do [ -f \"$f\" ] && echo \"$f: $(cat $f)\"; done 2>&1",
                timeout=30
            )
            logger.info(f"[PRE-CHECK] Current PTP devices:\n{result.stdout}")
            
            # Check current ENA module parameters
            result = ssh_manager.execute_command(
                connection,
                "cat /sys/module/ena/parameters/* 2>&1 | head -20",
                timeout=30
            )
            logger.info(f"[PRE-CHECK] Current ENA module parameters:\n{result.stdout}")
            
            # Check hardware timestamping before
            result = ssh_manager.execute_command(
                connection,
                "ip -o link show | grep -E 'enp[0-9]+s[0-9]+' | head -1 | awk '{print $2}' | tr -d ':'",
                timeout=30
            )
            interface = result.stdout.strip() if result.success else "eth0"
            
            result = ssh_manager.execute_command(
                connection,
                f"sudo ethtool -T {interface} 2>&1 | grep -E 'PTP Hardware Clock|Transmit Timestamp'",
                timeout=30
            )
            logger.info(f"[PRE-CHECK] Hardware timestamping on {interface}:\n{result.stdout}")
            
            # Step 1: Ensure PTP module is loaded
            logger.info("\n[STEP 1] Ensuring PTP module is loaded...")
            result = ssh_manager.execute_command(
                connection,
                "sudo modprobe ptp && sudo modprobe pps_core",
                timeout=30
            )
            
            if not result.success:
                logger.warning(f"[STEP 1] Could not load PTP modules: {result.stderr}")
                logger.info("[STEP 1] Modules might be built-in, continuing...")
            else:
                logger.info("[STEP 1] ✓ PTP modules loaded successfully")
            
            # Verify modules
            result = ssh_manager.execute_command(
                connection,
                "lsmod | grep -E 'ptp|pps_core'",
                timeout=30
            )
            logger.info(f"[STEP 1] Loaded modules:\n{result.stdout}")
            
            # Step 2: Get PCI address of ENA device
            logger.info("\n[STEP 2] Getting ENA device PCI address...")
            result = ssh_manager.execute_command(
                connection,
                "lspci -D | grep 'Ethernet controller.*ENA' | awk '{print $1}'",
                timeout=30
            )
            
            if not result.success or not result.stdout.strip():
                logger.error("[STEP 2] ✗ Could not find ENA device PCI address")
                return (False, False)
            
            pci_address = result.stdout.strip()
            logger.info(f"[STEP 2] ✓ Found ENA device at PCI address: {pci_address}")
            
            # Get detailed PCI device info
            result = ssh_manager.execute_command(
                connection,
                f"lspci -vvv -s {pci_address} 2>&1 | head -30",
                timeout=30
            )
            logger.info(f"[STEP 2] ENA device details:\n{result.stdout}")
            
            # Step 3: Try devlink approach first (Linux 6.16+)
            logger.info("\n[STEP 3] Attempting to enable PHC via devlink...")
            result = ssh_manager.execute_command(
                connection,
                f"sudo devlink dev param set pci/{pci_address} name enable_phc value true cmode driverinit 2>&1",
                timeout=30
            )
            
            if result.success:
                logger.info("[STEP 3] ✓ PHC parameter set via devlink")
                logger.info(f"[STEP 3] Devlink output: {result.stdout}")
                
                # Verify parameter was set
                result = ssh_manager.execute_command(
                    connection,
                    f"sudo devlink dev param show pci/{pci_address} name enable_phc 2>&1",
                    timeout=30
                )
                logger.info(f"[STEP 3] PHC parameter verification:\n{result.stdout}")
                
                # Reload driver via devlink
                logger.info("[STEP 3] Reloading driver via devlink...")
                reload_result = ssh_manager.execute_command(
                    connection,
                    f"sudo devlink dev reload pci/{pci_address}",
                    timeout=60
                )
                
                if reload_result.success:
                    logger.info("[STEP 3] ✓ Driver reloaded successfully via devlink")
                    
                    # POST-CHECK after devlink reload
                    time.sleep(3)
                    
                    logger.info("\n[POST-CHECK] Verifying PHC enablement after devlink reload...")
                    result = ssh_manager.execute_command(
                        connection,
                        "ls -la /dev/ptp* 2>&1; echo '---'; for f in /sys/class/ptp/*/clock_name; do [ -f \"$f\" ] && echo \"$f: $(cat $f)\"; done 2>&1",
                        timeout=30
                    )
                    logger.info(f"[POST-CHECK] PTP devices after reload:\n{result.stdout}")
                    
                    result = ssh_manager.execute_command(
                        connection,
                        f"sudo ethtool -T {interface} 2>&1 | grep -E 'PTP Hardware Clock|Transmit Timestamp'",
                        timeout=30
                    )
                    logger.info(f"[POST-CHECK] Hardware timestamping after reload:\n{result.stdout}")
                    
                    # Check if ena-ptp device was created
                    result = ssh_manager.execute_command(
                        connection,
                        "grep -r 'ena-ptp' /sys/class/ptp/*/clock_name 2>/dev/null",
                        timeout=30
                    )
                    
                    if result.success and result.stdout.strip():
                        logger.info(f"[POST-CHECK] ✓ ENA PTP device created: {result.stdout}")
                        logger.info("=" * 80)
                        logger.info("PHC ENABLEMENT SUCCESSFUL VIA DEVLINK")
                        logger.info("=" * 80)
                        return (True, False)  # Success, no reconnect needed
                    else:
                        logger.warning("[POST-CHECK] ✗ ENA PTP device NOT created after devlink reload")
                        logger.info("[POST-CHECK] Falling back to module parameter approach...")
                else:
                    logger.warning(f"[STEP 3] ✗ Devlink reload failed: {reload_result.stderr}")
                    logger.info("[STEP 3] Falling back to module parameter approach...")
            else:
                logger.info(f"[STEP 3] Devlink not available: {result.stderr}")
                logger.info("[STEP 3] Trying module parameter approach...")
            
            # Step 4: Fallback to module parameter approach
            logger.info("\n[STEP 4] Enabling PHC via module parameter...")
            logger.warning(
                "[STEP 4] ⚠️  Module reload will drop SSH connection! "
                "Reconnection will be attempted automatically."
            )
            
            # Create a comprehensive reload script with detailed logging
            reload_script = r"""#!/bin/bash
exec > /tmp/ena_phc_reload.log 2>&1
echo "=== ENA PHC Reload Script Started at $(date) ==="
echo ""

echo "[1] Capturing pre-reload state..."
echo "Current PTP devices:"
ls -la /dev/ptp* 2>&1
echo ""
echo "Current PTP sysfs entries:"
for f in /sys/class/ptp/*/clock_name; do [ -f "$f" ] && echo "$f: $(cat $f)"; done 2>&1
echo ""
echo "Current ENA module info:"
modinfo ena | head -10
echo ""

echo "[2] Unloading ENA module..."
rmmod ena
RMMOD_EXIT=$?
echo "rmmod exit code: $RMMOD_EXIT"
sleep 2
echo ""

echo "[3] Loading ENA module with phc_enable=1..."
modprobe ena phc_enable=1
MODPROBE_EXIT=$?
echo "modprobe exit code: $MODPROBE_EXIT"
sleep 3
echo ""

echo "[4] Verifying PHC enablement..."
echo "New PTP devices:"
ls -la /dev/ptp* 2>&1
echo ""
echo "New PTP sysfs entries:"
for f in /sys/class/ptp/*/clock_name; do [ -f "$f" ] && echo "$f: $(cat $f)"; done 2>&1
echo ""
echo "ENA module parameters:"
cat /sys/module/ena/parameters/* 2>&1 | head -20
echo ""
echo "Check phc_enable value:"
[ -f /sys/module/ena/parameters/phc_enable ] && echo "phc_enable = $(cat /sys/module/ena/parameters/phc_enable)" || echo "Parameter not found"
echo ""

echo "[5] Checking dmesg for ENA/PTP messages..."
dmesg | grep -i 'ena\|ptp' | tail -20
echo ""

echo "=== ENA PHC Reload Script Completed at $(date) ==="
"""
            
            # Write the script
            result = ssh_manager.execute_command(
                connection,
                f"cat > /tmp/ena_phc_reload.sh <<'EOFSCRIPT'\n{reload_script}EOFSCRIPT\nchmod +x /tmp/ena_phc_reload.sh",
                timeout=30
            )
            
            if not result.success:
                logger.error(f"[STEP 4] ✗ Failed to create reload script: {result.stderr}")
                return (False, False)
            
            logger.info("[STEP 4] ✓ Reload script created at /tmp/ena_phc_reload.sh")
            
            # Execute the script in background with nohup
            logger.info("[STEP 4] Executing reload script...")
            result = ssh_manager.execute_command(
                connection,
                "nohup sudo bash /tmp/ena_phc_reload.sh > /dev/null 2>&1 &",
                timeout=5
            )
            
            # Connection will drop during driver reload
            logger.info("[STEP 4] Driver reload initiated, SSH connection will drop...")
            logger.info("[STEP 4] Waiting 15 seconds for driver reload to complete...")
            
            # Wait for driver reload to complete
            time.sleep(15)
            
            # Signal that reconnection is needed
            logger.info("[STEP 4] Driver reload should be complete, reconnection required")
            logger.info("=" * 80)
            logger.info("PHC ENABLEMENT INITIATED VIA MODULE PARAMETER - RECONNECTION NEEDED")
            logger.info("=" * 80)
            return (True, True)  # Success, needs reconnect
                
        except Exception as e:
            logger.error(f"[ERROR] Failed to enable ENA PHC: {e}")
            logger.error("=" * 80)
            logger.error("PHC ENABLEMENT FAILED")
            logger.error("=" * 80)
            return (False, False)
    
    def compile_ena_driver_with_phc(
        self,
        ssh_manager: SSHManager,
        connection: SSHClient,
        instance_ip: str
    ) -> tuple[bool, bool]:
        """Compile and install ENA driver with PHC support enabled.
        
        The stock ENA driver on AL2023 does not have PHC support compiled in.
        According to AWS documentation and the ENA driver README, PHC support
        must be enabled at compile time using ENA_PHC_INCLUDE=1.
        
        This method:
        1. Detects CPU architecture (x86_64 or aarch64/ARM64)
        2. Installs build dependencies (kernel-devel, gcc, make, git)
        3. Clones the amzn-drivers repository
        4. Builds the ENA driver WITH PHC support (ENA_PHC_INCLUDE=1)
        5. Installs the compiled driver
        6. Creates a script to reload the driver with enable_phc=1
        7. Executes the reload script (which will drop SSH connection)
        
        Note: yum automatically handles architecture-specific packages (kernel-devel, gcc)
        based on the detected system architecture, so no special handling is needed.
        
        IMPORTANT: Driver reload will drop SSH connection!
        Caller must handle reconnection when needs_reconnect=True.
        
        References:
        - https://github.com/amzn/amzn-drivers/blob/master/kernel/linux/ena/README.rst
        - https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configure-ec2-ntp.html
        
        Args:
            ssh_manager: SSHManager instance for command execution
            connection: Active SSH connection to the instance
            instance_ip: Instance IP address for reconnection
            
        Returns:
            Tuple of (success: bool, needs_reconnect: bool)
            - success: True if compilation and installation successful
            - needs_reconnect: True if SSH connection was dropped and needs reconnection
        """
        logger.info("=" * 80)
        logger.info("COMPILING ENA DRIVER WITH PHC SUPPORT")
        logger.info("=" * 80)
        
        try:
            # Detect architecture at the start
            architecture = self.detect_architecture(ssh_manager, connection)
            logger.info(f"\n[ARCHITECTURE] Compiling ENA driver for architecture: {architecture}")
            logger.info(f"[ARCHITECTURE] Note: yum will automatically install {architecture}-specific packages")
            
            # Step 0: Check kernel PTP configuration prerequisites
            logger.info("\n[STEP 0] Checking kernel PTP configuration prerequisites...")
            result = ssh_manager.execute_command(
                connection,
                "grep -E 'CONFIG_PTP_1588_CLOCK|CONFIG_PPS' /boot/config-$(uname -r) 2>/dev/null",
                timeout=30
            )
            
            if result.success and result.stdout:
                logger.info("[STEP 0] Kernel PTP configuration:")
                for line in result.stdout.strip().split('\n'):
                    logger.info(f"  {line}")
                
                # Check if PTP support is enabled
                if 'CONFIG_PTP_1588_CLOCK=y' in result.stdout or 'CONFIG_PTP_1588_CLOCK=m' in result.stdout:
                    logger.info("[STEP 0] ✓ Kernel has PTP_1588_CLOCK support")
                else:
                    logger.warning(
                        "[STEP 0] ⚠️  Kernel may not have PTP_1588_CLOCK enabled. "
                        "PHC compilation might fail or be silently disabled."
                    )
                
                if 'CONFIG_PPS=y' in result.stdout or 'CONFIG_PPS=m' in result.stdout:
                    logger.info("[STEP 0] ✓ Kernel has PPS support")
                else:
                    logger.warning("[STEP 0] ⚠️  Kernel may not have PPS support")
            else:
                logger.warning(
                    "[STEP 0] ⚠️  Could not read kernel config. "
                    "Proceeding anyway, but PHC support may not work."
                )
            
            # Step 1: Install build dependencies
            logger.info("\n[STEP 1] Installing build dependencies...")
            result = ssh_manager.execute_command(
                connection,
                "sudo yum install -y kernel-devel-$(uname -r) gcc make git",
                timeout=300  # 5 minutes for package installation
            )
            
            if not result.success:
                logger.error(f"[STEP 1] ✗ Failed to install build dependencies: {result.stderr}")
                return (False, False)
            
            logger.info("[STEP 1] ✓ Build dependencies installed")
            
            # Step 2: Clone amzn-drivers repository
            logger.info("\n[STEP 2] Cloning amzn-drivers repository...")
            result = ssh_manager.execute_command(
                connection,
                "cd /tmp && rm -rf amzn-drivers && "
                "git clone https://github.com/amzn/amzn-drivers.git",
                timeout=180  # 3 minutes for git clone
            )
            
            if not result.success:
                logger.error(f"[STEP 2] ✗ Failed to clone repository: {result.stderr}")
                return (False, False)
            
            logger.info("[STEP 2] ✓ Repository cloned")
            
            # Step 3: Build the ENA driver WITH PHC support
            logger.info("\n[STEP 3] Building ENA driver with PHC support...")
            logger.info(f"[STEP 3] Target architecture: {architecture}")
            logger.info("[STEP 3] This may take 2-3 minutes...")
            logger.info("[STEP 3] Trying multiple build approaches to ensure PHC is enabled...")
            logger.info("[STEP 3] Note: Build tools will automatically compile for the detected architecture")
            
            # Try approach 1: ENA_PHC_INCLUDE=1 (original method)
            logger.info("[STEP 3.1] Attempting build with ENA_PHC_INCLUDE=1...")
            result = ssh_manager.execute_command(
                connection,
                "cd /tmp/amzn-drivers/kernel/linux/ena && make clean && make ENA_PHC_INCLUDE=1",
                timeout=300
            )
            
            if not result.success:
                logger.warning(f"[STEP 3.1] Build approach 1 failed: {result.stderr}")
                
                # Try approach 2: EXTRA_CFLAGS with -D flag
                logger.info("[STEP 3.2] Attempting build with EXTRA_CFLAGS...")
                result = ssh_manager.execute_command(
                    connection,
                    'cd /tmp/amzn-drivers/kernel/linux/ena && make clean && make EXTRA_CFLAGS="-DENA_PHC_INCLUDE=1"',
                    timeout=300
                )
                
                if not result.success:
                    logger.error(f"[STEP 3.2] ✗ Build approach 2 also failed: {result.stderr}")
                    return (False, False)
                else:
                    logger.info("[STEP 3.2] ✓ Build succeeded with EXTRA_CFLAGS approach")
            else:
                logger.info("[STEP 3.1] ✓ Build succeeded with ENA_PHC_INCLUDE approach")
            
            # Verify the compiled module has phc_enable parameter
            logger.info("[STEP 3.3] Verifying compiled module has phc_enable parameter...")
            result = ssh_manager.execute_command(
                connection,
                "modinfo /tmp/amzn-drivers/kernel/linux/ena/ena.ko 2>/dev/null | grep -i 'parm.*phc'",
                timeout=30
            )
            
            if result.success and 'phc' in result.stdout.lower():
                logger.info(f"[STEP 3.3] ✓ Compiled module has PHC parameter: {result.stdout.strip()}")
            else:
                logger.warning(
                    "[STEP 3.3] ⚠️  WARNING: Compiled module may not have PHC parameter! "
                    "This could indicate:\n"
                    "  1. Kernel lacks CONFIG_PTP_1588_CLOCK support\n"
                    "  2. Driver source doesn't support PHC in this version\n"
                    "  3. Build flags weren't properly applied\n"
                    "Proceeding with installation, but PHC may not work."
                )
                
                # Get full modinfo for diagnostics
                result = ssh_manager.execute_command(
                    connection,
                    "modinfo /tmp/amzn-drivers/kernel/linux/ena/ena.ko 2>/dev/null",
                    timeout=30
                )
                logger.info(f"[STEP 3.3] Compiled module info:\n{result.stdout[:500]}")
            
            logger.info("[STEP 3] ✓ ENA driver compilation complete")
            
            # Step 4: Install the compiled driver manually
            logger.info("\n[STEP 4] Installing compiled ENA driver...")
            
            # The ENA Makefile doesn't have an 'install' target, so we manually copy the .ko file
            # First, find the kernel module directory
            result = ssh_manager.execute_command(
                connection,
                "uname -r",
                timeout=30
            )
            
            if not result.success:
                logger.error(f"[STEP 4] ✗ Failed to get kernel version: {result.stderr}")
                return (False, False)
            
            kernel_version = result.stdout.strip()
            module_dir = f"/lib/modules/{kernel_version}/kernel/drivers/amazon/net/ena"
            
            logger.info(f"[STEP 4] Kernel version: {kernel_version}")
            logger.info(f"[STEP 4] Installing to: {module_dir}")
            
            # Create the module directory if it doesn't exist
            result = ssh_manager.execute_command(
                connection,
                f"sudo mkdir -p {module_dir}",
                timeout=30
            )
            
            if not result.success:
                logger.error(f"[STEP 4] ✗ Failed to create module directory: {result.stderr}")
                return (False, False)
            
            # Copy the compiled driver to the module directory
            result = ssh_manager.execute_command(
                connection,
                f"sudo cp /tmp/amzn-drivers/kernel/linux/ena/ena.ko {module_dir}/",
                timeout=30
            )
            
            if not result.success:
                logger.error(f"[STEP 4] ✗ Failed to copy driver module: {result.stderr}")
                return (False, False)
            
            # Update module dependencies
            result = ssh_manager.execute_command(
                connection,
                "sudo depmod -a",
                timeout=60
            )
            
            if not result.success:
                logger.error(f"[STEP 4] ✗ Failed to update module dependencies: {result.stderr}")
                return (False, False)
            
            logger.info("[STEP 4] ✓ ENA driver installed and module dependencies updated")
            
            # Step 5: Create driver reload script with PHC enabled
            logger.info("\n[STEP 5] Creating driver reload script with PHC enabled...")
            logger.warning(
                "[STEP 5] ⚠️  Driver reload will drop SSH connection! "
                "Reconnection will be attempted automatically."
            )
            
            reload_script = r"""#!/bin/bash
exec > /tmp/ena_driver_reload.log 2>&1
echo "=== ENA Driver Reload Script Started at $(date) ==="
echo ""

echo "[1] Capturing pre-reload state..."
echo "Current ENA driver version:"
modinfo ena | grep '^version:' || echo "Could not get version"
echo ""
echo "Current PTP devices:"
ls -la /dev/ptp* 2>&1
echo ""
echo "Current ENA module parameters:"
ls -la /sys/module/ena/parameters/ 2>&1
echo ""

echo "[2] Unloading ENA module..."
rmmod ena
RMMOD_EXIT=$?
echo "rmmod exit code: $RMMOD_EXIT"
sleep 2
echo ""

echo "[3] Loading NEW ENA module with phc_enable=1..."
modprobe ena phc_enable=1
MODPROBE_EXIT=$?
echo "modprobe exit code: $MODPROBE_EXIT"
sleep 3
echo ""

echo "[4] Verifying PHC enablement..."
echo "New ENA driver version:"
modinfo ena | grep '^version:' || echo "Could not get version"
echo ""
echo "Checking if phc_enable parameter exists in loaded module:"
modinfo ena | grep -i 'parm.*phc' || echo "✗ phc_enable parameter NOT FOUND in loaded module"
echo ""
echo "New PTP devices:"
ls -la /dev/ptp* 2>&1
echo ""
echo "New PTP sysfs entries:"
for f in /sys/class/ptp/*/clock_name; do [ -f "$f" ] && echo "$f: $(cat $f)"; done 2>&1
echo ""
echo "ENA module parameters:"
ls -la /sys/module/ena/parameters/ 2>&1
echo ""
echo "Check if phc_enable parameter exists:"
[ -f /sys/module/ena/parameters/phc_enable ] && echo "✓ phc_enable parameter EXISTS" || echo "✗ phc_enable parameter NOT FOUND"
echo ""
echo "Check phc_enable value:"
[ -f /sys/module/ena/parameters/phc_enable ] && echo "phc_enable = $(cat /sys/module/ena/parameters/phc_enable)" || echo "Parameter not found"
echo ""

echo "[5] Checking dmesg for ENA/PTP messages..."
dmesg | grep -i 'ena\|ptp' | tail -30
echo ""

echo "=== ENA Driver Reload Script Completed at $(date) ==="
"""
            
            # Write the reload script
            result = ssh_manager.execute_command(
                connection,
                f"cat > /tmp/ena_driver_reload.sh <<'EOFSCRIPT'\n{reload_script}EOFSCRIPT\nchmod +x /tmp/ena_driver_reload.sh",
                timeout=30
            )
            
            if not result.success:
                logger.error(f"[STEP 5] ✗ Failed to create reload script: {result.stderr}")
                return (False, False)
            
            logger.info("[STEP 5] ✓ Reload script created at /tmp/ena_driver_reload.sh")
            
            # Step 6: Execute the reload script in background
            logger.info("\n[STEP 6] Executing driver reload script...")
            result = ssh_manager.execute_command(
                connection,
                "nohup sudo bash /tmp/ena_driver_reload.sh > /dev/null 2>&1 &",
                timeout=5
            )
            
            # Connection will drop during driver reload
            logger.info("[STEP 6] Driver reload initiated, SSH connection will drop...")
            logger.info("[STEP 6] Waiting 15 seconds for driver reload to complete...")
            
            # Wait for driver reload to complete
            time.sleep(15)
            
            # Signal that reconnection is needed
            logger.info("[STEP 6] Driver reload should be complete, reconnection required")
            logger.info("=" * 80)
            logger.info("ENA DRIVER COMPILATION COMPLETE - RECONNECTION NEEDED")
            logger.info(f"[ARCHITECTURE] Compiled for: {architecture}")
            logger.info("=" * 80)
            return (True, True)  # Success, needs reconnect
                
        except Exception as e:
            logger.error(f"[ERROR] Failed to compile ENA driver with PHC: {e}")
            logger.error("=" * 80)
            logger.error("ENA DRIVER COMPILATION FAILED")
            logger.error(f"[ARCHITECTURE] Target architecture was: {architecture if 'architecture' in locals() else 'unknown'}")
            logger.error("=" * 80)
            return (False, False)
    
    def upgrade_ena_driver(
        self,
        ssh_manager: SSHManager,
        connection: SSHClient
    ) -> bool:
        """Upgrade ENA driver to version 2.10.0 or later.
        
        DEPRECATED: Use compile_ena_driver_with_phc() instead for PTP support.
        
        This method builds the driver without PHC support, which is not
        sufficient for PTP functionality. The compile_ena_driver_with_phc()
        method should be used instead.
        
        Args:
            ssh_manager: SSHManager instance for command execution
            connection: Active SSH connection to the instance
            
        Returns:
            True if upgrade successful, False otherwise
        """
        logger.warning(
            "upgrade_ena_driver() is deprecated for PTP use cases. "
            "Use compile_ena_driver_with_phc() instead to enable PHC support."
        )
        
        logger.info("Starting ENA driver upgrade process...")
        
        try:
            # Step 1: Install build dependencies
            logger.info("Installing build dependencies...")
            result = ssh_manager.execute_command(
                connection,
                "sudo yum install -y kernel-devel-$(uname -r) gcc make git",
                timeout=300  # 5 minutes for package installation
            )
            
            if not result.success:
                logger.error(f"Failed to install build dependencies: {result.stderr}")
                return False
            
            # Step 2: Clone amzn-drivers repository
            logger.info("Cloning amzn-drivers repository...")
            result = ssh_manager.execute_command(
                connection,
                "cd /tmp && rm -rf amzn-drivers && "
                "git clone https://github.com/amzn/amzn-drivers.git",
                timeout=180  # 3 minutes for git clone
            )
            
            if not result.success:
                logger.error(f"Failed to clone amzn-drivers repository: {result.stderr}")
                return False
            
            # Step 3: Build the ENA driver (WITHOUT PHC support)
            logger.info("Building ENA driver...")
            result = ssh_manager.execute_command(
                connection,
                "cd /tmp/amzn-drivers/kernel/linux/ena && make",
                timeout=300  # 5 minutes for build
            )
            
            if not result.success:
                logger.error(f"Failed to build ENA driver: {result.stderr}")
                return False
            
            # Step 4: Install the ENA driver
            logger.info("Installing ENA driver...")
            result = ssh_manager.execute_command(
                connection,
                "cd /tmp/amzn-drivers/kernel/linux/ena && sudo make install",
                timeout=120
            )
            
            if not result.success:
                logger.error(f"Failed to install ENA driver: {result.stderr}")
                return False
            
            # Step 5: Reload the driver module
            logger.info("Reloading ENA driver module...")
            result = ssh_manager.execute_command(
                connection,
                "sudo rmmod ena && sudo modprobe ena",
                timeout=30
            )
            
            if not result.success:
                logger.error(f"Failed to reload ENA driver: {result.stderr}")
                return False
            
            # Step 6: Verify the new version
            logger.info("Verifying new ENA driver version...")
            is_compatible, new_version = self.check_ena_driver_version(
                ssh_manager,
                connection
            )
            
            if is_compatible:
                logger.info(
                    f"ENA driver successfully upgraded to version {new_version}"
                )
                return True
            else:
                logger.error(
                    f"ENA driver upgrade completed but version {new_version} "
                    f"is still below minimum required version 2.10.0"
                )
                return False
                
        except Exception as e:
            logger.error(f"ENA driver upgrade failed with exception: {e}")
            return False
    
    def install_ptp_packages(
        self,
        ssh_manager: SSHManager,
        connection: SSHClient
    ) -> bool:
        """Install required PTP packages (chrony, linuxptp, ethtool).
        
        Args:
            ssh_manager: SSHManager instance for command execution
            connection: Active SSH connection to the instance
            
        Returns:
            True if installation successful, False otherwise
        """
        logger.info("Installing PTP packages (chrony, ethtool, and PTP tools)...")
        
        try:
            # First, check what PTP packages are available
            logger.info("Checking available PTP packages...")
            result = ssh_manager.execute_command(
                connection,
                "yum search ptp 2>&1 | grep -E '^(linuxptp|ptp)\\..*:' || echo 'No PTP packages found'",
                timeout=60
            )
            logger.info(f"Available PTP packages: {result.stdout}")
            
            # Install base packages (chrony and ethtool are always available)
            logger.info("Installing chrony and ethtool...")
            result = ssh_manager.execute_command(
                connection,
                "sudo yum install -y chrony ethtool",
                timeout=300
            )
            
            if not result.success:
                logger.error(f"Failed to install base packages: {result.stderr}")
                return False
            
            logger.info("✓ Base packages (chrony, ethtool) installed")
            
            # Try to install linuxptp (contains ptp4l and phc2sys)
            logger.info("Attempting to install linuxptp package...")
            result = ssh_manager.execute_command(
                connection,
                "sudo yum install -y linuxptp 2>&1",
                timeout=300
            )
            
            if result.success:
                logger.info("✓ linuxptp package installed successfully")
            else:
                logger.warning(f"linuxptp package not available: {result.stderr}")
                logger.info("Checking if ptp4l and phc2sys are already available...")
                
                # Check if ptp4l and phc2sys are already installed
                result = ssh_manager.execute_command(
                    connection,
                    "which ptp4l && which phc2sys",
                    timeout=30
                )
                
                if result.success:
                    logger.info("✓ ptp4l and phc2sys are already available on the system")
                else:
                    logger.warning(
                        "PTP tools (ptp4l, phc2sys) are not available in package repos. "
                        "Building linuxptp from source..."
                    )
                    
                    # Build linuxptp from source
                    if not self._build_linuxptp_from_source(ssh_manager, connection):
                        logger.error("Failed to build linuxptp from source")
                        return False
            
            logger.info("PTP package installation complete")
            return True
            
        except Exception as e:
            logger.error(f"PTP package installation failed with exception: {e}")
            return False
    
    def _build_linuxptp_from_source(
        self,
        ssh_manager: SSHManager,
        connection: SSHClient
    ) -> bool:
        """Build linuxptp tools (ptp4l, phc2sys) from source.
        
        This is needed when linuxptp package is not available in repos,
        which can happen on newer kernels or certain AMI versions.
        
        Args:
            ssh_manager: SSHManager instance for command execution
            connection: Active SSH connection to the instance
            
        Returns:
            True if build and installation successful, False otherwise
        """
        logger.info("Building linuxptp from source...")
        
        try:
            # Step 1: Install build dependencies
            logger.info("Installing build dependencies for linuxptp...")
            result = ssh_manager.execute_command(
                connection,
                "sudo yum install -y gcc make git kernel-headers kernel-devel",
                timeout=300
            )
            
            if not result.success:
                logger.error(f"Failed to install build dependencies: {result.stderr}")
                return False
            
            logger.info("✓ Build dependencies installed")
            
            # Step 2: Clone linuxptp repository
            logger.info("Cloning linuxptp repository...")
            result = ssh_manager.execute_command(
                connection,
                "cd /tmp && rm -rf linuxptp && "
                "git clone https://git.code.sf.net/p/linuxptp/code linuxptp",
                timeout=180
            )
            
            if not result.success:
                logger.warning(f"Failed to clone from sourceforge, trying GitHub mirror...")
                result = ssh_manager.execute_command(
                    connection,
                    "cd /tmp && rm -rf linuxptp && "
                    "git clone https://github.com/richardcochran/linuxptp.git",
                    timeout=180
                )
                
                if not result.success:
                    logger.error(f"Failed to clone linuxptp repository: {result.stderr}")
                    return False
            
            logger.info("✓ Repository cloned")
            
            # Step 3: Build linuxptp
            logger.info("Building linuxptp (this may take 2-3 minutes)...")
            result = ssh_manager.execute_command(
                connection,
                "cd /tmp/linuxptp && make clean && make",
                timeout=300
            )
            
            if not result.success:
                logger.error(f"Failed to build linuxptp: {result.stderr}")
                return False
            
            logger.info("✓ linuxptp built successfully")
            
            # Step 4: Install binaries
            logger.info("Installing linuxptp binaries...")
            result = ssh_manager.execute_command(
                connection,
                "cd /tmp/linuxptp && sudo make install",
                timeout=60
            )
            
            if not result.success:
                logger.error(f"Failed to install linuxptp: {result.stderr}")
                return False
            
            logger.info("✓ linuxptp installed to /usr/local/sbin")
            
            # Step 5: Verify installation
            logger.info("Verifying linuxptp installation...")
            result = ssh_manager.execute_command(
                connection,
                "which ptp4l && which phc2sys && ptp4l -v",
                timeout=30
            )
            
            if not result.success:
                logger.error(f"linuxptp tools not found after installation: {result.stderr}")
                return False
            
            logger.info(f"✓ linuxptp tools verified: {result.stdout.strip()}")
            
            # Step 6: Create systemd service files
            logger.info("Creating systemd service files for ptp4l and phc2sys...")
            if not self._create_ptp_systemd_services(ssh_manager, connection):
                logger.error("Failed to create systemd service files")
                return False
            
            logger.info("✓ Systemd service files created")
            return True
                
        except Exception as e:
            logger.error(f"Failed to build linuxptp from source: {e}")
            return False
    
    def _create_ptp_systemd_services(
        self,
        ssh_manager: SSHManager,
        connection: SSHClient
    ) -> bool:
        """Create systemd service files for ptp4l and phc2sys.
        
        When building linuxptp from source, the systemd service files
        are not automatically created. This method creates them.
        
        Args:
            ssh_manager: SSHManager instance for command execution
            connection: Active SSH connection to the instance
            
        Returns:
            True if service files created successfully, False otherwise
        """
        try:
            # Create ptp4l systemd service file
            ptp4l_service = """[Unit]
Description=Precision Time Protocol (PTP) daemon
Documentation=man:ptp4l(8)
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/sbin/ptp4l -f /etc/ptp4l.conf
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
            
            result = ssh_manager.execute_command(
                connection,
                f"sudo tee /etc/systemd/system/ptp4l.service > /dev/null <<'EOF'\n{ptp4l_service}EOF",
                timeout=30
            )
            
            if not result.success:
                logger.error(f"Failed to create ptp4l.service: {result.stderr}")
                return False
            
            logger.info("✓ Created /etc/systemd/system/ptp4l.service")
            
            # Create phc2sys systemd service file
            phc2sys_service = """[Unit]
Description=Synchronize system clock to PTP Hardware Clock (PHC)
Documentation=man:phc2sys(8)
After=ptp4l.service
Requires=ptp4l.service

[Service]
Type=simple
ExecStart=/usr/local/sbin/phc2sys -s /dev/ptp0 -c CLOCK_REALTIME -w -m -R 8
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
            
            result = ssh_manager.execute_command(
                connection,
                f"sudo tee /etc/systemd/system/phc2sys.service > /dev/null <<'EOF'\n{phc2sys_service}EOF",
                timeout=30
            )
            
            if not result.success:
                logger.error(f"Failed to create phc2sys.service: {result.stderr}")
                return False
            
            logger.info("✓ Created /etc/systemd/system/phc2sys.service")
            
            # Reload systemd to pick up new service files
            logger.info("Reloading systemd daemon...")
            result = ssh_manager.execute_command(
                connection,
                "sudo systemctl daemon-reload",
                timeout=30
            )
            
            if not result.success:
                logger.error(f"Failed to reload systemd: {result.stderr}")
                return False
            
            logger.info("✓ Systemd daemon reloaded")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create systemd service files: {e}")
            return False
    
    def check_hardware_timestamping_state(
        self,
        ssh_manager: SSHManager,
        connection: SSHClient
    ) -> tuple[bool, str]:
        """Check the current hardware packet timestamping state via sysfs.
        
        Hardware packet timestamping is disabled by default on all ENIs.
        This method checks the current state via the sysfs interface.
        
        Args:
            ssh_manager: SSHManager instance for command execution
            connection: Active SSH connection to the instance
            
        Returns:
            Tuple of (is_enabled, diagnostic_info)
        """
        logger.info("Checking hardware packet timestamping state...")
        
        try:
            # Find PCI address of ENA device
            result = ssh_manager.execute_command(
                connection,
                "lspci -D | grep -i ethernet | awk '{print $1}'",
                timeout=30
            )
            
            if not result.success or not result.stdout.strip():
                logger.warning("Could not find PCI address of ENA device")
                return False, "PCI address not found"
            
            pci_addr = result.stdout.strip()
            logger.info(f"Found ENA device at PCI address: {pci_addr}")
            
            # Check if sysfs attribute exists
            sysfs_path = f"/sys/bus/pci/devices/{pci_addr}/hw_packet_timestamping_state"
            result = ssh_manager.execute_command(
                connection,
                f"cat {sysfs_path} 2>&1",
                timeout=30
            )
            
            if not result.success:
                logger.warning(
                    f"Could not read hw_packet_timestamping_state from sysfs. "
                    f"This may be normal on some kernel versions. Output: {result.stdout}"
                )
                return False, f"sysfs attribute not available: {result.stdout}"
            
            state = result.stdout.strip()
            is_enabled = state == "1"
            
            if is_enabled:
                logger.info("Hardware packet timestamping is ENABLED")
            else:
                logger.info("Hardware packet timestamping is DISABLED (default state)")
            
            return is_enabled, f"State: {state} (0=disabled, 1=enabled)"
            
        except Exception as e:
            logger.warning(f"Error checking hardware timestamping state: {e}")
            return False, f"Error: {str(e)}"
    
    def enable_hardware_timestamping(
        self,
        ssh_manager: SSHManager,
        connection: SSHClient,
        interface: str = "eth0"
    ) -> bool:
        """Enable PTP hardware timestamping on the network interface.
        
        Hardware packet timestamping is disabled by default on all ENIs.
        This method:
        1. Verifies hardware timestamping capabilities
        2. Checks for ENA PTP hardware clock device
        3. ACTUALLY ENABLES hardware timestamping using ethtool
        4. Verifies enablement was successful
        
        CRITICAL: This must be called BEFORE starting ptp4l, as ptp4l requires
        hardware timestamping to be enabled on the interface.
        
        Args:
            ssh_manager: SSHManager instance for command execution
            connection: Active SSH connection to the instance
            interface: Network interface name (default: eth0)
            
        Returns:
            True if hardware timestamping enabled successfully, False otherwise
        """
        logger.info(f"Enabling hardware timestamping on {interface}...")
        
        try:
            # Step 1: Check if the interface supports hardware timestamping
            logger.info(f"[STEP 1] Checking if {interface} supports hardware timestamping...")
            result = ssh_manager.execute_command(
                connection,
                f"sudo ethtool -T {interface}",
                timeout=30
            )
            
            if not result.success:
                logger.error(
                    f"Failed to query timestamping capabilities: {result.stderr}"
                )
                return False
            
            # Check if hardware timestamping is supported
            if "hardware-transmit" not in result.stdout and "PTP Hardware Clock" not in result.stdout:
                logger.error(
                    f"Interface {interface} does not support hardware timestamping. "
                    f"Output: {result.stdout}"
                )
                return False
            
            logger.info(f"✓ Interface {interface} supports hardware timestamping")
            
            # Step 2: Check if ENA PTP hardware clock device exists via sysfs
            logger.info("[STEP 2] Checking for ENA PTP hardware clock device...")
            result = ssh_manager.execute_command(
                connection,
                "for file in /sys/class/ptp/*/clock_name; do echo -n \"$file: \"; cat \"$file\" 2>/dev/null; done 2>/dev/null",
                timeout=30
            )
            
            if "ena-ptp" not in result.stdout:
                logger.error(
                    "No ENA PTP hardware clock device found. The ENA driver may not have "
                    "created the PTP device. This could indicate:\n"
                    "1. The instance type does not support PTP hardware\n"
                    "2. The ENA driver needs to be reloaded\n"
                    "3. Additional kernel modules need to be loaded"
                )
                return False
            
            logger.info(f"✓ ENA PTP hardware clock device found: {result.stdout.strip()}")
            
            # Step 3: Check current hardware packet timestamping state (before enabling)
            logger.info("[STEP 3] Checking current hardware timestamping state...")
            is_enabled_before, state_info_before = self.check_hardware_timestamping_state(
                ssh_manager,
                connection
            )
            
            logger.info(f"Hardware timestamping state BEFORE enablement: {state_info_before}")
            
            if is_enabled_before:
                logger.info("✓ Hardware timestamping is already enabled")
                return True
            
            # Step 4: ACTUALLY ENABLE hardware timestamping using ethtool
            logger.info("[STEP 4] Enabling hardware timestamping using ethtool...")
            logger.info(f"Executing: sudo ethtool --set-phc-hwts {interface} on")
            
            result = ssh_manager.execute_command(
                connection,
                f"sudo ethtool --set-phc-hwts {interface} on",
                timeout=30
            )
            
            if not result.success:
                logger.error(
                    f"Failed to enable hardware timestamping: {result.stderr}\n"
                    f"This could indicate:\n"
                    f"1. ethtool version doesn't support --set-phc-hwts option\n"
                    f"2. The ENA driver doesn't support this operation\n"
                    f"3. Insufficient permissions\n"
                    f"Attempting alternative method..."
                )
                
                # Try alternative: use ethtool -s to set timestamping
                logger.info("Trying alternative method: ethtool -s...")
                result = ssh_manager.execute_command(
                    connection,
                    f"sudo ethtool -s {interface} phc_hwts on",
                    timeout=30
                )
                
                if not result.success:
                    logger.error(
                        f"Alternative method also failed: {result.stderr}\n"
                        f"Hardware timestamping enablement failed. ptp4l may not work correctly."
                    )
                    return False
            
            logger.info("✓ Hardware timestamping enablement command executed")
            
            # Step 5: Verify hardware timestamping was actually enabled
            logger.info("[STEP 5] Verifying hardware timestamping was enabled...")
            time.sleep(1)  # Brief pause to let the change take effect
            
            is_enabled_after, state_info_after = self.check_hardware_timestamping_state(
                ssh_manager,
                connection
            )
            
            logger.info(f"Hardware timestamping state AFTER enablement: {state_info_after}")
            
            if not is_enabled_after:
                logger.warning(
                    "⚠️  Hardware timestamping enablement command succeeded, but verification "
                    "shows it's still not enabled. This may indicate:\n"
                    "1. The change requires a brief delay to take effect\n"
                    "2. The interface doesn't support persistent enablement\n"
                    "3. ptp4l will need to enable it via HWTSTAMP ioctl when it starts\n"
                    "Proceeding anyway - ptp4l may still work."
                )
            else:
                logger.info("✓ Hardware timestamping successfully enabled and verified!")
            
            # Step 6: Display final ethtool output for diagnostics
            logger.info("[STEP 6] Final hardware timestamping configuration:")
            result = ssh_manager.execute_command(
                connection,
                f"sudo ethtool -T {interface}",
                timeout=30
            )
            
            if result.success:
                logger.info(f"ethtool -T {interface} output:\n{result.stdout}")
            
            return True
                
        except Exception as e:
            logger.error(f"Hardware timestamping enablement failed with exception: {e}")
            return False
    
    def configure_ptp4l(
        self,
        ssh_manager: SSHManager,
        connection: SSHClient,
        interface: str = "eth0"
    ) -> bool:
        """Configure and start ptp4l daemon.
        
        Creates /etc/ptp4l.conf with proper settings and starts the ptp4l service.
        ptp4l will automatically enable hardware packet timestamping via HWTSTAMP ioctl.
        
        Args:
            ssh_manager: SSHManager instance for command execution
            connection: Active SSH connection to the instance
            interface: Network interface name (default: eth0)
            
        Returns:
            True if configuration successful, False otherwise
        """
        logger.info("Configuring ptp4l daemon...")
        
        try:
            # Create ptp4l configuration file
            ptp4l_config = f"""[global]
slaveOnly 1
priority1 128
priority2 128
domainNumber 0

[{interface}]
network_transport L2
delay_mechanism E2E
"""
            
            # Write configuration file
            result = ssh_manager.execute_command(
                connection,
                f"sudo tee /etc/ptp4l.conf > /dev/null <<'EOF'\n{ptp4l_config}EOF",
                timeout=30
            )
            
            if not result.success:
                logger.error(f"Failed to create ptp4l.conf: {result.stderr}")
                return False
            
            logger.info("Created /etc/ptp4l.conf")
            
            # Start and enable ptp4l service
            logger.info("Starting ptp4l service...")
            logger.info(
                "Note: ptp4l will enable hardware packet timestamping via HWTSTAMP ioctl. "
                "This causes a momentary network disruption."
            )
            result = ssh_manager.execute_command(
                connection,
                "sudo systemctl start ptp4l && sudo systemctl enable ptp4l",
                timeout=60
            )
            
            if not result.success:
                logger.error(f"Failed to start ptp4l service: {result.stderr}")
                return False
            
            logger.info("ptp4l service started and enabled")
            
            # Wait a moment for ptp4l to enable hardware timestamping
            time.sleep(2)
            
            # Verify hardware packet timestamping was enabled
            is_enabled, state_info = self.check_hardware_timestamping_state(
                ssh_manager,
                connection
            )
            
            if is_enabled:
                logger.info("Hardware packet timestamping successfully enabled by ptp4l")
            else:
                logger.warning(
                    f"Hardware packet timestamping may not be enabled yet. {state_info}. "
                    "This may be normal if sysfs attribute is not available on this kernel version."
                )
            
            return True
            
        except Exception as e:
            logger.error(f"ptp4l configuration failed: {e}")
            return False
    
    def configure_phc2sys(
        self,
        ssh_manager: SSHManager,
        connection: SSHClient
    ) -> bool:
        """Configure and start phc2sys daemon.
        
        Creates /etc/sysconfig/phc2sys configuration and starts the service.
        phc2sys synchronizes the system clock with the PTP hardware clock.
        
        Args:
            ssh_manager: SSHManager instance for command execution
            connection: Active SSH connection to the instance
            
        Returns:
            True if configuration successful, False otherwise
        """
        logger.info("Configuring phc2sys daemon...")
        
        try:
            # Create phc2sys configuration
            phc2sys_config = 'OPTIONS="-a -r -r"'
            
            # Ensure /etc/sysconfig directory exists
            result = ssh_manager.execute_command(
                connection,
                "sudo mkdir -p /etc/sysconfig",
                timeout=30
            )
            
            if not result.success:
                logger.error(f"Failed to create /etc/sysconfig directory: {result.stderr}")
                return False
            
            # Write configuration file
            result = ssh_manager.execute_command(
                connection,
                f"sudo tee /etc/sysconfig/phc2sys > /dev/null <<'EOF'\n{phc2sys_config}\nEOF",
                timeout=30
            )
            
            if not result.success:
                logger.error(f"Failed to create phc2sys config: {result.stderr}")
                return False
            
            logger.info("Created /etc/sysconfig/phc2sys")
            
            # Start and enable phc2sys service
            logger.info("Starting phc2sys service...")
            result = ssh_manager.execute_command(
                connection,
                "sudo systemctl start phc2sys && sudo systemctl enable phc2sys",
                timeout=60
            )
            
            if not result.success:
                logger.error(f"Failed to start phc2sys service: {result.stderr}")
                return False
            
            logger.info("phc2sys service started and enabled")
            return True
            
        except Exception as e:
            logger.error(f"phc2sys configuration failed: {e}")
            return False
    
    def create_ptp_ena_symlink(
        self,
        ssh_manager: SSHManager,
        connection: SSHClient
    ) -> bool:
        """Create /dev/ptp_ena symlink for consistent PTP device naming.
        
        AWS ENA PTP devices are named /dev/ptp0, /dev/ptp1, etc., with the index
        depending on hardware initialization order. Creating a symlink ensures
        applications like chrony consistently reference the correct device.
        
        Latest Amazon Linux 2023 AMIs include a udev rule that creates this symlink
        automatically. This method creates it if missing.
        
        Args:
            ssh_manager: SSHManager instance for command execution
            connection: Active SSH connection to the instance
            
        Returns:
            True if symlink exists or was created successfully, False otherwise
        """
        logger.info("Checking for /dev/ptp_ena symlink...")
        
        try:
            # Check if symlink already exists
            result = ssh_manager.execute_command(
                connection,
                "ls -l /dev/ptp* 2>&1",
                timeout=30
            )
            
            if "/dev/ptp_ena" in result.stdout:
                logger.info("✓ /dev/ptp_ena symlink already exists")
                return True
            
            logger.info("/dev/ptp_ena symlink not found, creating it...")
            
            # Add udev rule
            udev_rule = 'SUBSYSTEM=="ptp", ATTR{clock_name}=="ena-ptp-*", SYMLINK += "ptp_ena"'
            result = ssh_manager.execute_command(
                connection,
                f'echo \'{udev_rule}\' | sudo tee -a /etc/udev/rules.d/53-ec2-network-interfaces.rules',
                timeout=30
            )
            
            if not result.success:
                logger.error(f"Failed to add udev rule: {result.stderr}")
                return False
            
            logger.info("✓ Added udev rule for /dev/ptp_ena")
            
            # Reload udev rules
            result = ssh_manager.execute_command(
                connection,
                "sudo udevadm control --reload-rules && sudo udevadm trigger",
                timeout=30
            )
            
            if not result.success:
                logger.error(f"Failed to reload udev rules: {result.stderr}")
                return False
            
            logger.info("✓ Reloaded udev rules")
            
            # Wait a moment for symlink creation
            time.sleep(2)
            
            # Verify symlink was created
            result = ssh_manager.execute_command(
                connection,
                "ls -l /dev/ptp_ena 2>&1",
                timeout=30
            )
            
            if result.success and "/dev/ptp_ena" in result.stdout:
                logger.info(f"✓ /dev/ptp_ena symlink created successfully: {result.stdout.strip()}")
                return True
            else:
                logger.warning("Symlink creation may have failed, but continuing...")
                return False
                
        except Exception as e:
            logger.error(f"Failed to create /dev/ptp_ena symlink: {e}")
            return False
    
    def configure_chrony(
        self,
        ssh_manager: SSHManager,
        connection: SSHClient
    ) -> bool:
        """Configure chrony to use PTP hardware clock via /dev/ptp_ena symlink.
        
        This implements the AWS ENA PTP architecture where chrony directly reads
        from the PTP hardware clock, NOT the traditional ptp4l/phc2sys approach.
        
        AWS ENA PTP Architecture:
        PTP Hardware Clock (/dev/ptp_ena) → chrony → System Clock
        
        Args:
            ssh_manager: SSHManager instance for command execution
            connection: Active SSH connection to the instance
            
        Returns:
            True if configuration successful, False otherwise
        """
        logger.info("Configuring chrony to use PTP hardware clock...")
        
        try:
            # Check if /dev/ptp_ena exists, if not try /dev/ptp0
            result = ssh_manager.execute_command(
                connection,
                "test -e /dev/ptp_ena && echo '/dev/ptp_ena' || echo '/dev/ptp0'",
                timeout=30
            )
            
            ptp_device = result.stdout.strip() if result.success else "/dev/ptp0"
            logger.info(f"Using PTP device: {ptp_device}")
            
            # Add PHC refclock line to chrony.conf if not already present
            logger.info("Adding PHC refclock to /etc/chrony.conf...")
            
            # Check if PHC refclock already configured
            result = ssh_manager.execute_command(
                connection,
                "grep -q 'refclock PHC' /etc/chrony.conf && echo 'exists' || echo 'not found'",
                timeout=30
            )
            
            if "exists" in result.stdout:
                logger.info("PHC refclock already configured in chrony.conf")
            else:
                # Add PHC refclock line
                phc_line = f"refclock PHC {ptp_device} poll 0 delay 0.000010 prefer"
                result = ssh_manager.execute_command(
                    connection,
                    f"echo '{phc_line}' | sudo tee -a /etc/chrony.conf",
                    timeout=30
                )
                
                if not result.success:
                    logger.error(f"Failed to add PHC refclock to chrony.conf: {result.stderr}")
                    return False
                
                logger.info(f"✓ Added PHC refclock line to chrony.conf: {phc_line}")
            
            # Restart chronyd service
            logger.info("Restarting chronyd service...")
            result = ssh_manager.execute_command(
                connection,
                "sudo systemctl restart chronyd",
                timeout=60
            )
            
            if not result.success:
                logger.error(f"Failed to restart chronyd service: {result.stderr}")
                return False
            
            logger.info("✓ chronyd service restarted")
            
            # Wait for chrony to stabilize
            time.sleep(3)
            
            return True
            
        except Exception as e:
            logger.error(f"chrony configuration failed: {e}")
            return False
    
    def verify_ptp(
        self,
        ssh_manager: SSHManager,
        connection: SSHClient,
        ena_driver_version: Optional[str] = None
    ) -> PTPStatus:
        """Verify PTP functionality and gather diagnostic information.
        
        This method:
        1. Checks for /dev/ptp* devices
        2. Verifies ptp4l is running
        3. Verifies phc2sys is running
        4. Checks chrony synchronization status
        5. Gathers diagnostic output from all services
        
        Args:
            ssh_manager: SSHManager instance for command execution
            connection: Active SSH connection to the instance
            ena_driver_version: ENA driver version (if already known)
            
        Returns:
            PTPStatus object with all verification results and diagnostics
        """
        logger.info("Verifying PTP functionality...")
        
        diagnostic_output = {}
        
        # Get ENA driver version if not provided
        if ena_driver_version is None:
            try:
                is_compatible, ena_driver_version = self.check_ena_driver_version(
                    ssh_manager,
                    connection
                )
                ena_driver_compatible = is_compatible
            except Exception as e:
                logger.warning(f"Could not check ENA driver version: {e}")
                ena_driver_version = None
                ena_driver_compatible = False
        else:
            ena_driver_compatible = self._compare_version(
                ena_driver_version,
                self.MIN_ENA_VERSION
            )
        
        # Check for ENA PTP hardware clock devices via sysfs
        logger.info("Checking for ENA PTP hardware clock devices...")
        result = ssh_manager.execute_command(
            connection,
            "for file in /sys/class/ptp/*/clock_name; do echo -n \"$file: \"; cat \"$file\" 2>/dev/null; done 2>/dev/null",
            timeout=30
        )
        diagnostic_output['ptp_devices'] = result.stdout
        
        hardware_clock_present = result.success and 'ena-ptp' in result.stdout
        clock_device = None
        
        if hardware_clock_present:
            # Check for /dev/ptp_ena symlink first (preferred for consistent naming)
            symlink_result = ssh_manager.execute_command(
                connection,
                "test -L /dev/ptp_ena && echo 'exists' || echo 'not found'",
                timeout=30
            )
            
            if symlink_result.success and 'exists' in symlink_result.stdout:
                clock_device = "/dev/ptp_ena"
                logger.info(f"Using /dev/ptp_ena symlink for consistent device naming")
            else:
                # Fall back to extracting PTP index from sysfs path
                match = re.search(r'/sys/class/ptp/(ptp\d+)/clock_name', result.stdout)
                if match:
                    ptp_index = match.group(1)
                    clock_device = f"/dev/{ptp_index}"
                    logger.info(f"Found ENA PTP hardware clock device: {clock_device}")
                    logger.info(f"Note: /dev/ptp_ena symlink not found. Consider using latest AL2023 AMI with udev rule.")
        else:
            logger.warning("No ENA PTP hardware clock devices found")
        
        # Detect the primary network interface
        interface = self.get_primary_network_interface(ssh_manager, connection)
        logger.info(f"Using network interface: {interface}")
        diagnostic_output['detected_interface'] = interface
        
        # Check hardware timestamping status
        logger.info(f"Checking hardware timestamping status on {interface}...")
        result = ssh_manager.execute_command(
            connection,
            f"sudo ethtool -T {interface} 2>&1",
            timeout=30
        )
        diagnostic_output['ethtool'] = result.stdout
        
        # Check hardware packet timestamping state via sysfs
        is_hw_ts_enabled, hw_ts_state = self.check_hardware_timestamping_state(
            ssh_manager,
            connection
        )
        diagnostic_output['hw_packet_timestamping_state'] = hw_ts_state
        
        # Check for /dev/ptp_ena symlink (AWS ENA PTP best practice)
        logger.info("Checking for /dev/ptp_ena symlink...")
        result = ssh_manager.execute_command(
            connection,
            "ls -l /dev/ptp* 2>&1",
            timeout=30
        )
        diagnostic_output['ptp_devices_list'] = result.stdout
        
        ptp_ena_symlink_present = "/dev/ptp_ena" in result.stdout
        
        # Check chrony sources to see if it's using PHC
        logger.info("Checking if chrony is using PTP hardware clock...")
        result = ssh_manager.execute_command(
            connection,
            "chronyc sources 2>&1",
            timeout=30
        )
        diagnostic_output['chrony_sources'] = result.stdout
        
        # Check if PHC0 appears as the preferred time source (indicated by #*)
        # Expected output line: #* PHC0                          0   0    377    1   +2ns[ +1ns] +/-   5031ns
        chrony_using_phc = result.success and "#* PHC0" in result.stdout
        
        if chrony_using_phc:
            logger.info("✓ Chrony is using PHC0 as the preferred time source")
        else:
            logger.warning("Chrony is not using PHC0 as the preferred time source")
        
        # Check chrony synchronization status
        logger.info("Checking chrony synchronization...")
        result = ssh_manager.execute_command(
            connection,
            "chronyc tracking 2>&1",
            timeout=30
        )
        diagnostic_output['chrony_tracking'] = result.stdout
        
        # Check for positive synchronization status
        chrony_synchronized = result.success and "Reference ID" in result.stdout
        
        # Try to get time offset if hardware clock is present
        time_offset_ns = None
        if hardware_clock_present and clock_device:
            result = ssh_manager.execute_command(
                connection,
                f"sudo phc_ctl {clock_device} get 2>&1",
                timeout=30
            )
            diagnostic_output['phc_ctl'] = result.stdout
            
            # Try to parse time offset from output
            # Output format varies, but we're looking for offset information
            if result.success:
                # This is a best-effort parse; actual format may vary
                match = re.search(r'offset[:\s]+(-?\d+)', result.stdout)
                if match:
                    try:
                        time_offset_ns = float(match.group(1))
                    except ValueError:
                        pass
        
        # Determine overall PTP support status using AWS ENA PTP architecture
        # AWS ENA PTP uses chrony directly with PHC, NOT ptp4l/phc2sys
        supported = (
            hardware_clock_present and
            ena_driver_compatible and
            chrony_using_phc
        )
        
        # Generate error message if not supported
        error_message = None
        if not supported:
            reasons = []
            if not ena_driver_compatible:
                reasons.append(
                    f"ENA driver version {ena_driver_version} is below "
                    f"minimum required version 2.10.0"
                )
            if not hardware_clock_present:
                reasons.append("No PTP hardware clock devices found")
            if not chrony_using_phc:
                reasons.append("Chrony is not using PHC0 as preferred time source")
            
            error_message = "; ".join(reasons)
            logger.warning(f"PTP not supported: {error_message}")
        else:
            logger.info("PTP is functional on this instance")
        
        return PTPStatus(
            supported=supported,
            ena_driver_version=ena_driver_version,
            ena_driver_compatible=ena_driver_compatible,
            hardware_clock_present=hardware_clock_present,
            ptp_ena_symlink_present=ptp_ena_symlink_present,
            chrony_using_phc=chrony_using_phc,
            chrony_synchronized=chrony_synchronized,
            clock_device=clock_device,
            time_offset_ns=time_offset_ns,
            error_message=error_message,
            diagnostic_output=diagnostic_output
        )

    def verify_phc_enablement_post_reload(
        self,
        ssh_manager: SSHManager,
        connection: SSHClient
    ) -> tuple[bool, dict]:
        """Verify PHC enablement after driver reload.
        
        This method should be called after reconnecting following a driver reload
        that was supposed to enable PHC support. It checks:
        1. /dev/ptp* devices exist
        2. ENA PTP clock is registered in sysfs
        3. phc_enable parameter is set correctly
        
        Args:
            ssh_manager: SSHManager instance for command execution
            connection: Active SSH connection to the instance
            
        Returns:
            Tuple of (success: bool, diagnostics: dict)
        """
        logger.info("=" * 80)
        logger.info("VERIFYING PHC ENABLEMENT AFTER DRIVER RELOAD")
        logger.info("=" * 80)
        
        diagnostics = {}
        success = True
        
        # Check 1: Verify /dev/ptp* devices exist
        logger.info("\n[CHECK 1] Verifying /dev/ptp* devices...")
        result = ssh_manager.execute_command(
            connection,
            "ls -la /dev/ptp* 2>&1",
            timeout=30
        )
        
        diagnostics['ptp_devices'] = result.stdout
        ptp_device_exists = result.success and '/dev/ptp' in result.stdout
        
        if ptp_device_exists:
            logger.info(f"[CHECK 1] ✓ PTP device exists:\n{result.stdout}")
        else:
            logger.error(f"[CHECK 1] ✗ No PTP devices found:\n{result.stdout}")
            success = False
        
        # Check 2: Verify ENA PTP clock in sysfs
        logger.info("\n[CHECK 2] Verifying ENA PTP clock in sysfs...")
        result = ssh_manager.execute_command(
            connection,
            "for f in /sys/class/ptp/*/clock_name; do [ -f \"$f\" ] && echo \"$f: $(cat $f)\"; done 2>&1",
            timeout=30
        )
        
        diagnostics['ptp_sysfs'] = result.stdout
        ena_ptp_exists = 'ena-ptp' in result.stdout
        
        if ena_ptp_exists:
            logger.info(f"[CHECK 2] ✓ ENA PTP clock registered:\n{result.stdout}")
        else:
            logger.error(f"[CHECK 2] ✗ ENA PTP clock not found in sysfs:\n{result.stdout}")
            success = False
        
        # Check 3: Verify phc_enable parameter
        logger.info("\n[CHECK 3] Verifying phc_enable parameter...")
        result = ssh_manager.execute_command(
            connection,
            "cat /sys/module/ena/parameters/phc_enable 2>&1",
            timeout=30
        )
        
        diagnostics['phc_enable_value'] = result.stdout.strip()
        phc_enabled = result.success and result.stdout.strip() == '1'
        
        if phc_enabled:
            logger.info(f"[CHECK 3] ✓ phc_enable parameter is set to 1")
        else:
            logger.warning(f"[CHECK 3] ⚠️  phc_enable parameter value: {result.stdout.strip()}")
            # Don't fail on this - parameter might not exist on some driver versions
        
        # Check 4: Verify hardware timestamping capabilities
        logger.info("\n[CHECK 4] Verifying hardware timestamping capabilities...")
        interface = self.get_primary_network_interface(ssh_manager, connection)
        result = ssh_manager.execute_command(
            connection,
            f"sudo ethtool -T {interface} 2>&1 | grep -E 'PTP Hardware Clock|Transmit Timestamp'",
            timeout=30
        )
        
        diagnostics['hardware_timestamping'] = result.stdout
        has_hw_ts = 'PTP Hardware Clock' in result.stdout or 'hardware-transmit' in result.stdout
        
        if has_hw_ts:
            logger.info(f"[CHECK 4] ✓ Hardware timestamping capabilities present:\n{result.stdout}")
        else:
            logger.warning(f"[CHECK 4] ⚠️  Hardware timestamping status:\n{result.stdout}")
        
        # Summary
        logger.info("\n" + "=" * 80)
        if success:
            logger.info("PHC ENABLEMENT VERIFICATION: SUCCESS")
            logger.info("✓ PTP device exists")
            logger.info("✓ ENA PTP clock registered")
        else:
            logger.error("PHC ENABLEMENT VERIFICATION: FAILED")
            if not ptp_device_exists:
                logger.error("✗ PTP device not found")
            if not ena_ptp_exists:
                logger.error("✗ ENA PTP clock not registered")
        logger.info("=" * 80)
        
        return success, diagnostics

    def get_phc_reload_diagnostics(
        self,
        ssh_manager: SSHManager,
        connection: SSHClient
    ) -> str:
        """Retrieve diagnostics from the PHC reload script log.
        
        This method should be called after reconnecting following a PHC enablement
        that required driver reload. It retrieves the detailed log created by the
        reload script.
        
        Args:
            ssh_manager: SSHManager instance for command execution
            connection: Active SSH connection to the instance
            
        Returns:
            String containing the reload log contents, or error message if not found
        """
        logger.info("Retrieving PHC reload diagnostics...")
        
        # Try to get the driver reload log
        result = ssh_manager.execute_command(
            connection,
            "cat /tmp/ena_driver_reload.log 2>&1",
            timeout=30
        )
        
        if result.success and result.stdout.strip():
            logger.info("=" * 80)
            logger.info("DRIVER RELOAD DIAGNOSTICS FROM /tmp/ena_driver_reload.log")
            logger.info("=" * 80)
            logger.info(result.stdout)
            logger.info("=" * 80)
            
            # Also check for the PHC reload log (from enable_ena_phc method)
            result2 = ssh_manager.execute_command(
                connection,
                "cat /tmp/ena_phc_reload.log 2>&1",
                timeout=30
            )
            
            if result2.success and result2.stdout.strip():
                logger.info("=" * 80)
                logger.info("PHC RELOAD DIAGNOSTICS FROM /tmp/ena_phc_reload.log")
                logger.info("=" * 80)
                logger.info(result2.stdout)
                logger.info("=" * 80)
                return result.stdout + "\n\n" + result2.stdout
            
            return result.stdout
        else:
            logger.warning("Could not retrieve driver reload log")
            
            # Try the PHC reload log as fallback
            result = ssh_manager.execute_command(
                connection,
                "cat /tmp/ena_phc_reload.log 2>&1",
                timeout=30
            )
            
            if result.success and result.stdout.strip():
                logger.info("=" * 80)
                logger.info("PHC RELOAD DIAGNOSTICS FROM /tmp/ena_phc_reload.log")
                logger.info("=" * 80)
                logger.info(result.stdout)
                logger.info("=" * 80)
                return result.stdout
            
            return "No reload logs found"
    
    def troubleshoot_ptp_issues(
        self,
        ssh_manager: SSHManager,
        connection: SSHClient
    ) -> dict:
        """Perform comprehensive troubleshooting for PTP configuration issues.
        
        This method checks all prerequisites and common configuration issues
        based on AWS documentation and ENA driver requirements:
        - Kernel version compatibility
        - Required kernel modules
        - ENA driver configuration
        - PTP device creation
        - Network interface configuration
        - Service status and logs
        
        Args:
            ssh_manager: SSHManager instance for command execution
            connection: Active SSH connection to the instance
            
        Returns:
            Dictionary with troubleshooting results and recommendations
        """
        logger.info("Starting comprehensive PTP troubleshooting...")
        
        troubleshooting_results = {
            'checks': [],
            'issues_found': [],
            'recommendations': []
        }
        
        # Detect the primary network interface
        interface = self.get_primary_network_interface(ssh_manager, connection)
        logger.info(f"Using network interface: {interface}")
        
        # Check 1: Kernel version
        logger.info("Checking kernel version...")
        result = ssh_manager.execute_command(
            connection,
            "uname -r",
            timeout=30
        )
        
        kernel_version = result.stdout.strip() if result.success else "Unknown"
        troubleshooting_results['checks'].append({
            'name': 'Kernel Version',
            'status': 'pass' if result.success else 'fail',
            'value': kernel_version,
            'details': 'Kernel version detected'
        })
        
        # Check 2: Required kernel modules (with auto-remediation)
        logger.info("Checking required kernel modules...")
        required_modules = ['ptp', 'pps_core']
        
        for module in required_modules:
            result = ssh_manager.execute_command(
                connection,
                f"lsmod | grep -w {module}",
                timeout=30
            )
            
            module_loaded = result.success and module in result.stdout
            
            if not module_loaded:
                # Auto-remediation: Try to load the module
                logger.info(f"Module {module} not loaded, attempting to load it...")
                load_result = ssh_manager.execute_command(
                    connection,
                    f"sudo modprobe {module}",
                    timeout=30
                )
                
                if load_result.success:
                    # Verify it loaded - check both lsmod and module existence in /sys
                    verify_result = ssh_manager.execute_command(
                        connection,
                        f"lsmod | grep -w {module} || test -d /sys/module/{module}",
                        timeout=30
                    )
                    module_loaded = verify_result.success
                    
                    if module_loaded:
                        logger.info(f"✓ Successfully loaded module {module}")
                        troubleshooting_results['checks'].append({
                            'name': f'Kernel Module: {module}',
                            'status': 'pass',
                            'value': 'Loaded (auto-fixed)',
                            'details': f"Module {module} was not loaded but has been loaded automatically"
                        })
                    else:
                        # Module might be built-in, check if modprobe succeeded without error
                        logger.info(f"Module {module} modprobe succeeded (may be built-in)")
                        troubleshooting_results['checks'].append({
                            'name': f'Kernel Module: {module}',
                            'status': 'pass',
                            'value': 'Available (built-in or loaded)',
                            'details': f"Module {module} is available (modprobe succeeded)"
                        })
                else:
                    logger.warning(f"Failed to load module {module}: {load_result.stderr}")
                    troubleshooting_results['checks'].append({
                        'name': f'Kernel Module: {module}',
                        'status': 'fail',
                        'value': 'Not loaded',
                        'details': f"Module {module} is not loaded and auto-load failed: {load_result.stderr[:100]}"
                    })
                    troubleshooting_results['issues_found'].append(
                        f"Kernel module '{module}' is not loaded and could not be loaded automatically"
                    )
                    troubleshooting_results['recommendations'].append(
                        f"Manually load kernel module: sudo modprobe {module}"
                    )
            else:
                troubleshooting_results['checks'].append({
                    'name': f'Kernel Module: {module}',
                    'status': 'pass',
                    'value': 'Loaded',
                    'details': f"Module {module} is loaded"
                })
        
        # Check 3: ENA driver module parameters
        logger.info("Checking ENA driver module parameters...")
        result = ssh_manager.execute_command(
            connection,
            "cat /sys/module/ena/parameters/enable_ptp 2>&1",
            timeout=30
        )
        
        if result.success and result.stdout.strip():
            ptp_enabled = result.stdout.strip() == 'Y'
            troubleshooting_results['checks'].append({
                'name': 'ENA PTP Parameter',
                'status': 'pass' if ptp_enabled else 'fail',
                'value': result.stdout.strip(),
                'details': f"ENA driver PTP parameter: {result.stdout.strip()}"
            })
            
            if not ptp_enabled:
                troubleshooting_results['issues_found'].append(
                    "ENA driver PTP support is disabled via module parameter"
                )
                troubleshooting_results['recommendations'].append(
                    "Reload ENA driver with PTP enabled: sudo rmmod ena && sudo modprobe ena"
                )
        else:
            troubleshooting_results['checks'].append({
                'name': 'ENA PTP Parameter',
                'status': 'warn',
                'value': 'Not available',
                'details': 'Could not read ENA PTP parameter (may not be supported on this driver version)'
            })
        
        # Check 4: PCI device information
        logger.info("Checking PCI device information...")
        result = ssh_manager.execute_command(
            connection,
            "lspci -vvv -d 1d0f:* 2>&1 | grep -A 20 'Ethernet controller'",
            timeout=30
        )
        
        if result.success:
            troubleshooting_results['checks'].append({
                'name': 'ENA PCI Device',
                'status': 'pass',
                'value': 'Found',
                'details': result.stdout[:200]  # First 200 chars
            })
        else:
            troubleshooting_results['checks'].append({
                'name': 'ENA PCI Device',
                'status': 'fail',
                'value': 'Not found',
                'details': 'Could not find ENA PCI device'
            })
            troubleshooting_results['issues_found'].append(
                "ENA PCI device not found - this may not be an ENA-enabled instance"
            )
        
        # Check 5: ENA PTP sysfs entries (PRIMARY check per AWS docs)
        logger.info("Checking ENA PTP sysfs entries...")
        result = ssh_manager.execute_command(
            connection,
            "for file in /sys/class/ptp/*/clock_name; do echo -n \"$file: \"; cat \"$file\" 2>/dev/null; done 2>/dev/null",
            timeout=30
        )
        
        ena_ptp_found = 'ena-ptp' in result.stdout
        ptp_index = None
        
        if ena_ptp_found:
            # Extract PTP index from sysfs path
            import re
            match = re.search(r'/sys/class/ptp/(ptp\d+)/clock_name', result.stdout)
            if match:
                ptp_index = match.group(1)
        
        troubleshooting_results['checks'].append({
            'name': 'ENA PTP Sysfs Entry',
            'status': 'pass' if ena_ptp_found else 'fail',
            'value': result.stdout.strip() if ena_ptp_found else 'Not found',
            'details': f'ENA PTP hardware clock in sysfs{f" ({ptp_index})" if ptp_index else ""}'
        })
        
        if not ena_ptp_found:
            troubleshooting_results['issues_found'].append(
                "No ENA PTP hardware clock found in sysfs (/sys/class/ptp/*/clock_name)"
            )
            troubleshooting_results['recommendations'].append(
                "This instance type may not support PTP hardware, or the ENA driver needs to be reloaded"
            )
        
        # Check 6: PTP character device (SECONDARY check - should exist if sysfs entry exists)
        logger.info("Checking PTP character devices...")
        result = ssh_manager.execute_command(
            connection,
            "ls -la /dev/ptp* 2>&1",
            timeout=30
        )
        
        ptp_dev_exists = '/dev/ptp' in result.stdout
        
        # Determine status based on sysfs check
        if ena_ptp_found and not ptp_dev_exists:
            status = 'warn'  # Sysfs exists but /dev doesn't - unusual but may work
            details = 'Sysfs entry exists but /dev node missing (may be normal on some kernels)'
        elif ptp_dev_exists:
            status = 'pass'
            details = f'PTP device node in /dev: {result.stdout.strip()}'
        else:
            status = 'fail'
            details = 'No PTP device node in /dev'
        
        troubleshooting_results['checks'].append({
            'name': 'PTP Character Device (/dev/ptp*)',
            'status': status,
            'value': result.stdout.strip() if ptp_dev_exists else 'Not found',
            'details': details
        })
        
        if ena_ptp_found and not ptp_dev_exists:
            troubleshooting_results['recommendations'].append(
                f"ENA PTP found in sysfs but /dev/{ptp_index} missing - this may be normal depending on kernel version"
            )
        
        # Check 6a: /dev/ptp_ena symlink (IMPORTANT for consistent device naming)
        logger.info("Checking /dev/ptp_ena symlink...")
        result = ssh_manager.execute_command(
            connection,
            "ls -la /dev/ptp_ena 2>&1",
            timeout=30
        )
        
        ptp_ena_symlink_exists = result.success and '/dev/ptp_ena' in result.stdout
        
        if ptp_ena_symlink_exists:
            # Extract what the symlink points to
            symlink_target = None
            if '->' in result.stdout:
                symlink_target = result.stdout.split('->')[-1].strip()
            
            troubleshooting_results['checks'].append({
                'name': '/dev/ptp_ena Symlink',
                'status': 'pass',
                'value': f'Present -> {symlink_target}' if symlink_target else 'Present',
                'details': f'Symlink exists for consistent device naming: {result.stdout.strip()}'
            })
        else:
            status = 'warn' if ena_ptp_found else 'info'
            troubleshooting_results['checks'].append({
                'name': '/dev/ptp_ena Symlink',
                'status': status,
                'value': 'Not found',
                'details': 'The /dev/ptp_ena symlink is not present. Latest AL2023 AMIs include a udev rule that creates this symlink.'
            })
            
            if ena_ptp_found:
                troubleshooting_results['recommendations'].append(
                    "Consider creating /dev/ptp_ena symlink for consistent device naming. "
                    "Latest Amazon Linux 2023 AMIs include a udev rule for this."
                )
        
        # Check 7: Network interface status
        logger.info("Checking network interface status...")
        result = ssh_manager.execute_command(
            connection,
            f"ip link show {interface}",
            timeout=30
        )
        
        if result.success:
            interface_up = 'UP' in result.stdout
            troubleshooting_results['checks'].append({
                'name': f'Network Interface {interface}',
                'status': 'pass' if interface_up else 'warn',
                'value': 'UP' if interface_up else 'DOWN',
                'details': result.stdout.strip()
            })
            
            if not interface_up:
                troubleshooting_results['issues_found'].append(
                    f"Network interface {interface} is down"
                )
                troubleshooting_results['recommendations'].append(
                    f"Bring up network interface: sudo ip link set {interface} up"
                )
        
        # Check 8: Service logs for errors
        logger.info("Checking service logs for errors...")
        services = ['ptp4l', 'phc2sys', 'chronyd']
        
        for service in services:
            result = ssh_manager.execute_command(
                connection,
                f"sudo journalctl -u {service} -n 50 --no-pager 2>&1 | grep -i error",
                timeout=30
            )
            
            if result.success and result.stdout.strip():
                troubleshooting_results['checks'].append({
                    'name': f'{service} Service Errors',
                    'status': 'warn',
                    'value': 'Errors found',
                    'details': result.stdout[:300]  # First 300 chars
                })
                troubleshooting_results['issues_found'].append(
                    f"Errors found in {service} logs"
                )
                troubleshooting_results['recommendations'].append(
                    f"Review full logs: sudo journalctl -u {service} -n 100"
                )
            else:
                troubleshooting_results['checks'].append({
                    'name': f'{service} Service Errors',
                    'status': 'pass',
                    'value': 'No errors',
                    'details': f'No errors in recent {service} logs'
                })
        
        # Check 9: dmesg for ENA/PTP related errors
        logger.info("Checking dmesg for ENA/PTP errors...")
        result = ssh_manager.execute_command(
            connection,
            "sudo dmesg | grep -i 'ena\\|ptp' | tail -20",
            timeout=30
        )
        
        if result.success and result.stdout.strip():
            has_errors = 'error' in result.stdout.lower() or 'fail' in result.stdout.lower()
            troubleshooting_results['checks'].append({
                'name': 'Kernel Messages (dmesg)',
                'status': 'warn' if has_errors else 'info',
                'value': 'Messages found',
                'details': result.stdout[:400]  # First 400 chars
            })
            
            if has_errors:
                troubleshooting_results['issues_found'].append(
                    "Errors found in kernel messages related to ENA/PTP"
                )
                troubleshooting_results['recommendations'].append(
                    "Review full kernel messages: sudo dmesg | grep -i 'ena\\|ptp'"
                )
        
        # Check 10: Hardware timestamping capabilities
        logger.info("Checking hardware timestamping capabilities...")
        result = ssh_manager.execute_command(
            connection,
            f"sudo ethtool -T {interface} 2>&1",
            timeout=30
        )
        
        if result.success:
            has_hw_ts = 'hardware-transmit' in result.stdout or 'PTP Hardware Clock' in result.stdout
            troubleshooting_results['checks'].append({
                'name': 'Hardware Timestamping Capabilities',
                'status': 'pass' if has_hw_ts else 'fail',
                'value': 'Supported' if has_hw_ts else 'Not supported',
                'details': result.stdout[:300]
            })
            
            if not has_hw_ts:
                troubleshooting_results['issues_found'].append(
                    f"Network interface {interface} does not report hardware timestamping capabilities"
                )
                troubleshooting_results['recommendations'].append(
                    "This instance type may not support hardware timestamping"
                )
        
        # Check 11: PCI device information
        logger.info("Checking PCI device information...")
        result = ssh_manager.execute_command(
            connection,
            "lspci -D | grep -i ethernet",
            timeout=30
        )
        
        if result.success and result.stdout.strip():
            troubleshooting_results['checks'].append({
                'name': 'PCI Ethernet Device',
                'status': 'info',
                'value': 'Found',
                'details': result.stdout.strip()
            })
        
        # Check 12: ENA module parameters
        logger.info("Checking ENA module parameters...")
        result = ssh_manager.execute_command(
            connection,
            "ls -la /sys/module/ena/parameters/ 2>/dev/null",
            timeout=30
        )
        
        if result.success and result.stdout.strip():
            troubleshooting_results['checks'].append({
                'name': 'ENA Module Parameters',
                'status': 'info',
                'value': 'Available',
                'details': result.stdout.strip()[:300]
            })
            
            # Check specific ENA parameters
            param_result = ssh_manager.execute_command(
                connection,
                "cat /sys/module/ena/parameters/* 2>/dev/null",
                timeout=30
            )
            if param_result.success and param_result.stdout.strip():
                troubleshooting_results['checks'].append({
                    'name': 'ENA Module Parameter Values',
                    'status': 'info',
                    'value': 'Retrieved',
                    'details': param_result.stdout.strip()[:200]
                })
        
        # Check 13: Hardware packet timestamping state (ENA-specific)
        logger.info("Checking ENA hardware packet timestamping state...")
        result = ssh_manager.execute_command(
            connection,
            "find /sys/bus/pci/devices -name 'hw_packet_timestamping_state' 2>/dev/null",
            timeout=30
        )
        
        if result.success and result.stdout.strip():
            hw_ts_path = result.stdout.strip()
            troubleshooting_results['checks'].append({
                'name': 'ENA Hardware Packet Timestamping State File',
                'status': 'info',
                'value': 'Found',
                'details': f'Path: {hw_ts_path}'
            })
            
            # Try to read the state
            state_result = ssh_manager.execute_command(
                connection,
                f"cat {hw_ts_path}",
                timeout=30
            )
            
            if state_result.success:
                state_value = state_result.stdout.strip()
                is_enabled = state_value == '1' or 'enabled' in state_value.lower()
                
                if not is_enabled:
                    # Auto-remediation: Try to enable hardware timestamping
                    logger.info("ENA hardware packet timestamping is disabled, attempting to enable...")
                    enable_result = ssh_manager.execute_command(
                        connection,
                        f"echo 1 | sudo tee {hw_ts_path}",
                        timeout=30
                    )
                    
                    if enable_result.success:
                        # Verify it was enabled
                        verify_result = ssh_manager.execute_command(
                            connection,
                            f"cat {hw_ts_path}",
                            timeout=30
                        )
                        
                        if verify_result.success:
                            new_state = verify_result.stdout.strip()
                            is_enabled = new_state == '1' or 'enabled' in new_state.lower()
                            
                            if is_enabled:
                                logger.info("✓ Successfully enabled ENA hardware packet timestamping")
                                troubleshooting_results['checks'].append({
                                    'name': 'ENA Hardware Packet Timestamping State',
                                    'status': 'pass',
                                    'value': 'Enabled (auto-fixed)',
                                    'details': f'Hardware timestamping was disabled but has been enabled automatically'
                                })
                            else:
                                logger.warning(f"Failed to enable hardware timestamping, state is still: {new_state}")
                                troubleshooting_results['checks'].append({
                                    'name': 'ENA Hardware Packet Timestamping State',
                                    'status': 'fail',
                                    'value': f'Enable failed ({new_state})',
                                    'details': f'Attempted to enable but state is still: {new_state}'
                                })
                                troubleshooting_results['issues_found'].append(
                                    "ENA hardware packet timestamping could not be enabled"
                                )
                        else:
                            logger.warning("Failed to verify hardware timestamping state after enabling")
                            troubleshooting_results['checks'].append({
                                'name': 'ENA Hardware Packet Timestamping State',
                                'status': 'warn',
                                'value': 'Verification failed',
                                'details': 'Enable command succeeded but verification failed'
                            })
                    else:
                        logger.warning(f"Failed to enable hardware timestamping: {enable_result.stderr}")
                        troubleshooting_results['checks'].append({
                            'name': 'ENA Hardware Packet Timestamping State',
                            'status': 'fail',
                            'value': f'Disabled ({state_value})',
                            'details': f'Hardware timestamping is disabled and auto-enable failed: {enable_result.stderr[:100]}'
                        })
                        troubleshooting_results['issues_found'].append(
                            "ENA hardware packet timestamping is disabled and could not be enabled automatically"
                        )
                        troubleshooting_results['recommendations'].append(
                            f"Manually enable hardware timestamping: echo 1 | sudo tee {hw_ts_path}"
                        )
                else:
                    troubleshooting_results['checks'].append({
                        'name': 'ENA Hardware Packet Timestamping State',
                        'status': 'pass',
                        'value': 'Enabled',
                        'details': f'State value: {state_value}'
                    })
        else:
            troubleshooting_results['checks'].append({
                'name': 'ENA Hardware Packet Timestamping State File',
                'status': 'warn',
                'value': 'Not found',
                'details': 'hw_packet_timestamping_state not found in sysfs - may not be supported on this instance type'
            })
            troubleshooting_results['recommendations'].append(
                "This instance type may not support ENA hardware packet timestamping"
            )
        
        # Summary
        total_checks = len(troubleshooting_results['checks'])
        passed_checks = sum(1 for c in troubleshooting_results['checks'] if c['status'] == 'pass')
        failed_checks = sum(1 for c in troubleshooting_results['checks'] if c['status'] == 'fail')
        
        troubleshooting_results['summary'] = {
            'total_checks': total_checks,
            'passed': passed_checks,
            'failed': failed_checks,
            'warnings': total_checks - passed_checks - failed_checks,
            'issues_count': len(troubleshooting_results['issues_found'])
        }
        
        logger.info(
            f"Troubleshooting complete: {passed_checks}/{total_checks} checks passed, "
            f"{len(troubleshooting_results['issues_found'])} issues found"
        )
        
        return troubleshooting_results
