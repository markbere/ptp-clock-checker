# PHC Enablement Diagnostics Enhancement

## Overview

Enhanced the PTP configurator with comprehensive diagnostics to debug why PHC (PTP Hardware Clock) enablement isn't fully working on r7i instances.

## Problem Analysis

From test results `ptp_test_results_20251203_005336.json`:

### What's Working ✅
- `/dev/ptp0` device created
- `PTP Hardware Clock: 0` detected by ethtool
- RX hardware timestamping: `HW RX support: 1`

### What's NOT Working ❌
- **TX hardware timestamping disabled**: `HW TX support: 0` (should be 1)
- **No ENA PTP device in sysfs**: Missing `ena-ptp-*` in `/sys/class/ptp/*/clock_name`
- **Hardware Transmit Timestamp Modes: none** (should show options)

### Root Cause Hypothesis

The `/dev/ptp0` device exists but it's **not the ENA PTP device** - it's likely a generic/software PTP device. The PHC enablement code is running but not actually enabling the ENA hardware PHC.

## Enhanced Diagnostics

### 1. Pre-Check Baseline Capture

Before any PHC enablement, we now capture:
- Current PTP devices (`/dev/ptp*` and `/sys/class/ptp/*/clock_name`)
- Current ENA module parameters
- Hardware timestamping capabilities (TX/RX support)

### 2. Step-by-Step Logging

Each step of PHC enablement now logs:
- **Step 1**: PTP module loading with verification
- **Step 2**: ENA PCI device detection with detailed info
- **Step 3**: Devlink approach attempt with parameter verification
- **Step 4**: Module parameter approach with comprehensive script

### 3. Detailed Reload Script

Created `/tmp/ena_phc_reload.sh` that logs:
```bash
[1] Pre-reload state (PTP devices, sysfs entries, module info)
[2] Module unload (rmmod ena) with exit code
[3] Module load with PHC (modprobe ena enable_phc=1) with exit code
[4] Post-reload verification (new PTP devices, sysfs entries, parameters)
[5] dmesg messages for ENA/PTP
```

### 4. Post-Reconnection Diagnostics

After SSH reconnection, we automatically:
- Retrieve the reload script log from `/tmp/ena_phc_reload.log`
- Display all diagnostic information
- Verify PHC enablement success

## Key Diagnostic Points

The enhanced logging will reveal:

1. **Is the PHC parameter actually being set?**
   - Check if `enable_phc=1` appears in module parameters after reload

2. **Does the driver reload succeed?**
   - Check rmmod and modprobe exit codes
   - Look for errors in the reload log

3. **Is the ENA PTP device created?**
   - Check if `ena-ptp-*` appears in `/sys/class/ptp/*/clock_name`
   - Verify `/dev/ptp*` is linked to ENA device

4. **What do dmesg messages show?**
   - Look for ENA driver initialization messages
   - Check for PTP-related kernel messages
   - Identify any errors or warnings

## Expected Output Format

```
================================================================================
STARTING PHC ENABLEMENT PROCESS - ENHANCED DIAGNOSTICS
================================================================================

[PRE-CHECK] Capturing baseline state before PHC enablement...
[PRE-CHECK] Current PTP devices:
<device listing>

[PRE-CHECK] Current ENA module parameters:
<parameter values>

[PRE-CHECK] Hardware timestamping on enp55s0:
<ethtool output>

[STEP 1] Ensuring PTP module is loaded...
[STEP 1] ✓ PTP modules loaded successfully

[STEP 2] Getting ENA device PCI address...
[STEP 2] ✓ Found ENA device at PCI address: 0000:37:00.0

[STEP 3] Attempting to enable PHC via devlink...
[STEP 3] Devlink not available: <error>
[STEP 3] Trying module parameter approach...

[STEP 4] Enabling PHC via module parameter...
[STEP 4] ⚠️  Module reload will drop SSH connection!
[STEP 4] ✓ Reload script created at /tmp/ena_phc_reload.sh
[STEP 4] Driver reload initiated, SSH connection will drop...

================================================================================
PHC ENABLEMENT INITIATED VIA MODULE PARAMETER - RECONNECTION NEEDED
================================================================================

<reconnection happens>

================================================================================
PHC RELOAD DIAGNOSTICS FROM /tmp/ena_phc_reload.log
================================================================================
=== ENA PHC Reload Script Started at <timestamp> ===

[1] Capturing pre-reload state...
<detailed state>

[2] Unloading ENA module...
rmmod exit code: 0

[3] Loading ENA module with phc_enable=1...
modprobe exit code: 0

[4] Verifying PHC enablement...
<verification results>

[5] Checking dmesg for ENA/PTP messages...
<kernel messages>

=== ENA PHC Reload Script Completed at <timestamp> ===
================================================================================
```

## Next Steps

1. **Run the enhanced test** to capture detailed diagnostics
2. **Analyze the reload log** to see:
   - If `phc_enable=1` is actually being set
   - If the driver reload succeeds
   - If the ENA PTP device is created
   - What dmesg shows about ENA/PTP initialization
3. **Identify the failure point** and adjust approach accordingly

## Possible Outcomes

### Scenario A: Parameter Not Set
If `enable_phc=1` doesn't appear in module parameters after reload:
- The parameter name might be wrong
- The parameter might not be supported on this driver version
- Need to check ENA driver source code for correct parameter name

### Scenario B: Device Not Created
If parameter is set but no `ena-ptp` device created:
- Instance type may not have PTP-capable hardware
- Driver may need additional configuration
- Kernel version may not support ENA PHC

### Scenario C: Permission/Timing Issue
If device is created but not accessible:
- May need to wait longer after reload
- May need to trigger device creation differently
- May need udev rules to create proper device nodes

## Files Modified

1. `src/ptp_tester/ptp_configurator.py`:
   - Enhanced `enable_ena_phc()` with comprehensive diagnostics
   - Added `get_phc_reload_diagnostics()` method

2. `src/ptp_tester/test_orchestrator.py`:
   - Added diagnostic retrieval after reconnection

## Testing

Run the test with:
```bash
python -m ptp_tester.cli test --instance-types r7i.16xlarge --region eu-north-1
```

The enhanced diagnostics will be visible in:
- Console output (logger.info messages)
- Test log files
- `/tmp/ena_phc_reload.log` on the instance (for manual inspection)
