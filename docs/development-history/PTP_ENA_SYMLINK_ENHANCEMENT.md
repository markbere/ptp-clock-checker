# PTP ENA Symlink Enhancement

## Overview
Enhanced PTP testing to properly detect and use the `/dev/ptp_ena` symlink for consistent PTP device naming, following AWS best practices for Amazon Linux 2023.

## Background

### The Problem
PTP devices are typically named `/dev/ptp0`, `/dev/ptp1`, etc., with their index depending on hardware initialization order. This can cause issues when:
- Multiple PTP devices exist on a system
- Device indices change between reboots
- Applications need consistent device references

### The Solution
Latest Amazon Linux 2023 AMIs include a udev rule that creates the `/dev/ptp_ena` symlink, pointing to the correct `/dev/ptp*` entry associated with the ENA host. This ensures:
- **Consistent device naming** across reboots
- **Reliable configuration** for chrony and other PTP applications
- **Validation** that the udev rule is working properly

## Implementation

### 1. Enhanced Diagnostics (ptp_configurator.py)

Added new diagnostic check for `/dev/ptp_ena` symlink:

```python
# Check 6a: /dev/ptp_ena symlink (IMPORTANT for consistent device naming)
logger.info("Checking /dev/ptp_ena symlink...")
result = ssh_manager.execute_command(
    connection,
    "ls -la /dev/ptp_ena 2>&1",
    timeout=30
)

ptp_ena_symlink_exists = result.success and '/dev/ptp_ena' in result.stdout
```

**Diagnostic Output:**
- **Status**: pass/warn/info
- **Value**: Shows symlink target (e.g., "Present -> ptp0")
- **Details**: Explains the importance of the symlink
- **Recommendations**: Suggests using latest AL2023 AMI if missing

### 2. Improved Device Detection (ptp_configurator.py)

Updated `verify_ptp()` to prefer `/dev/ptp_ena` when available:

```python
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
```

### 3. Updated Configuration Flow (test_orchestrator.py)

Enhanced PTP configuration to detect and use the correct device:

```python
# Detect the PTP device (prefer /dev/ptp_ena symlink for consistent naming)
logger.info("Detecting PTP device...")
ptp_device = "/dev/ptp0"  # Default fallback

# Check for /dev/ptp_ena symlink first (recommended for AL2023)
result = self.ssh_manager.execute_command(
    connection,
    "test -L /dev/ptp_ena && echo '/dev/ptp_ena' || ls /dev/ptp* 2>/dev/null | head -1",
    timeout=30
)

if result.success and result.stdout.strip():
    ptp_device = result.stdout.strip()
    logger.info(f"Using PTP device: {ptp_device}")
else:
    logger.warning(f"Could not detect PTP device, using default: {ptp_device}")

# Configure chrony with detected PTP device
if not self.ptp_configurator.configure_chrony(
    self.ssh_manager,
    connection,
    ptp_device=ptp_device
):
    logger.error("Failed to configure chrony")
```

## Benefits

1. **Consistent Device Naming**: Applications always reference the same device regardless of hardware initialization order
2. **Better Diagnostics**: Clear visibility into whether the udev rule is working
3. **Improved Reliability**: Reduces configuration errors from device index changes
4. **AWS Best Practices**: Follows official AWS documentation for PTP on EC2
5. **Backward Compatibility**: Falls back to `/dev/ptp0` if symlink doesn't exist

## Test Results

The enhancement will now report in diagnostics:

```json
{
  "name": "/dev/ptp_ena Symlink",
  "status": "pass",
  "value": "Present -> ptp0",
  "details": "Symlink exists for consistent device naming: lrwxrwxrwx 1 root root 4 Dec  2 21:30 /dev/ptp_ena -> ptp0"
}
```

Or if missing:

```json
{
  "name": "/dev/ptp_ena Symlink",
  "status": "warn",
  "value": "Not found",
  "details": "The /dev/ptp_ena symlink is not present. Latest AL2023 AMIs include a udev rule that creates this symlink."
}
```

## Recommendations

When `/dev/ptp_ena` is not found:
- Consider using the latest Amazon Linux 2023 AMI
- The udev rule should be present in recent AL2023 releases
- Manual symlink creation is possible but not recommended (udev rule is better)

## Related AWS Documentation

- AWS PTP documentation mentions the `/dev/ptp_ena` symlink
- Latest AL2023 AMIs include the udev rule automatically
- The symlink ensures consistent device naming across reboots

## Files Modified

1. `src/ptp_tester/ptp_configurator.py`:
   - Added `/dev/ptp_ena` symlink check in troubleshooting
   - Updated `verify_ptp()` to prefer symlink when available
   
2. `src/ptp_tester/test_orchestrator.py`:
   - Enhanced device detection in `_configure_ptp()`
   - Pass detected device to `configure_chrony()`

## Next Steps

- Test on instances with and without the symlink
- Verify chrony configuration uses the correct device
- Document the symlink requirement in user-facing documentation
