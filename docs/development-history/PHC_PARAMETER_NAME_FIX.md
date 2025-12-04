# PHC Parameter Name Fix - CRITICAL

## Problem Identified

The ENA driver reload was failing because we were using the **wrong parameter name**.

### Root Cause

From the test results and diagnostics:

```
ena: unknown parameter 'enable_phc' ignored
```

But the module actually has:
```
parm:           phc_enable:Enable PHC.
```

**The parameter is named `phc_enable`, NOT `enable_phc`!**

## Evidence

From the driver reload log (`ptp_tester_20251203_020506.log`):

```
Checking if enable_phc parameter exists in loaded module:
parm:           phc_enable:Enable PHC.

Check if enable_phc parameter exists:
✗ enable_phc parameter NOT FOUND
```

And from dmesg:
```
[   77.628306] ena: unknown parameter 'enable_phc' ignored
```

The compiled driver DOES have PHC support - we just weren't using the correct parameter name!

## Fix Applied

Updated both reload scripts in `src/ptp_tester/ptp_configurator.py`:

### 1. Driver Compilation Reload Script
Changed:
```bash
modprobe ena enable_phc=1
```

To:
```bash
modprobe ena phc_enable=1
```

### 2. PHC Enablement Reload Script  
Changed:
```bash
modprobe ena enable_phc=1
```

To:
```bash
modprobe ena phc_enable=1
```

### 3. Verification Checks
Updated all verification checks to look for `phc_enable` instead of `enable_phc`:
- Parameter existence checks
- modinfo grep patterns
- Log messages

## Expected Outcome

With this fix, the next test run should:

1. ✅ Compile the ENA driver with PHC support successfully
2. ✅ Load the module with `phc_enable=1` (correct parameter name)
3. ✅ Create `/dev/ptp0` device
4. ✅ Enable hardware timestamping
5. ✅ Allow ptp4l to synchronize with PTP grandmaster

## Testing

Run the test again:
```bash
python manual_test.py
```

The driver should now load with PHC enabled and create the PTP hardware clock device.

## Why This Happened

The AWS documentation and some examples use `enable_phc`, but the actual ENA driver source code uses `phc_enable`. This is a common issue with driver parameters where documentation doesn't match implementation.

Our enhanced diagnostics successfully identified this mismatch by:
1. Checking `modinfo` output for the actual parameter name
2. Capturing dmesg errors showing the parameter was ignored
3. Verifying parameter files in `/sys/module/ena/parameters/`

## Next Steps

1. Run test to verify PHC now works
2. If successful, update documentation to note the correct parameter name
3. Consider adding a check that tries both parameter names for robustness
