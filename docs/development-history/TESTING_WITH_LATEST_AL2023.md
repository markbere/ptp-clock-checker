# Testing with Latest AL2023 AMI and udev Rule

## Overview

The latest AL2023 AMIs include a udev rule that creates a `/dev/ptp_ena` symlink for consistent PTP device naming. This guide helps you test the PTP instance tester with this improvement.

## What's New in Latest AL2023

### udev Rule for PTP Device Symlink

Recent AL2023 AMIs include a udev rule that creates `/dev/ptp_ena` as a stable symlink to the ENA PTP device (e.g., `/dev/ptp0`).

**Benefits:**
- Consistent device naming across reboots
- No need to dynamically detect PTP device index
- Easier configuration management

**Location:** `/etc/udev/rules.d/`

**Expected symlink:**
```bash
ls -la /dev/ptp_ena
lrwxrwxrwx 1 root root 4 Dec  3 10:00 /dev/ptp_ena -> ptp0
```

## Current Implementation Support

The `verify_ptp()` method already checks for the `/dev/ptp_ena` symlink:

```python
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

## Testing Steps

### 1. Get Latest AL2023 AMI

Query SSM Parameter Store for the latest AL2023 AMI:

```bash
aws ssm get-parameters \
    --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
    --region us-west-2 \
    --query 'Parameters[0].Value' \
    --output text
```

Or let the tool auto-detect it (default behavior when no AMI specified).

### 2. Run Test with Latest AMI

```bash
# Test with auto-detected latest AMI
python -m ptp_tester.cli \
    --instance-type c7gn.xlarge \
    --subnet-id subnet-xxxxx \
    --key-path ~/.ssh/your-key.pem \
    --region us-west-2

# Or specify AMI explicitly
python -m ptp_tester.cli \
    --instance-type c7gn.xlarge \
    --subnet-id subnet-xxxxx \
    --key-path ~/.ssh/your-key.pem \
    --ami-id ami-xxxxx \
    --region us-west-2
```

### 3. Verify udev Rule Presence

After the test completes, check the diagnostic output for:

```json
{
  "clock_device": "/dev/ptp_ena",
  "diagnostic_output": {
    "ptp_devices": "/sys/class/ptp/ptp0/clock_name: ena-ptp"
  }
}
```

If `clock_device` is `/dev/ptp_ena`, the udev rule is present and working.

If `clock_device` is `/dev/ptp0` (or similar), the udev rule is not present.

### 4. Manual Verification on Instance

If you keep an instance running, SSH in and verify:

```bash
# Check for symlink
ls -la /dev/ptp_ena

# Check udev rules
ls -la /etc/udev/rules.d/ | grep ptp

# Check sysfs
cat /sys/class/ptp/ptp0/clock_name

# Verify services use the symlink
sudo systemctl status ptp4l
sudo systemctl status phc2sys
```

## Expected Behavior Differences

### With udev Rule (Latest AL2023)

**Advantages:**
- `/dev/ptp_ena` symlink exists
- Consistent device naming
- Configuration files can hardcode `/dev/ptp_ena`
- No dynamic device detection needed

**Log output:**
```
Using /dev/ptp_ena symlink for consistent device naming
```

**Result:**
```json
{
  "clock_device": "/dev/ptp_ena",
  "supported": true
}
```

### Without udev Rule (Older AL2023)

**Behavior:**
- Falls back to `/dev/ptp0` (or ptp1, ptp2, etc.)
- Device index may change across reboots
- Still functional, just less consistent

**Log output:**
```
Found ENA PTP hardware clock device: /dev/ptp0
Note: /dev/ptp_ena symlink not found. Consider using latest AL2023 AMI with udev rule.
```

**Result:**
```json
{
  "clock_device": "/dev/ptp0",
  "supported": true
}
```

## Troubleshooting

### Symlink Not Created After Driver Reload

If you reload the ENA driver and the symlink doesn't appear:

```bash
# Trigger udev rules manually
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=ptp

# Verify
ls -la /dev/ptp_ena
```

### Check udev Rule Content

```bash
# Find the rule
find /etc/udev/rules.d /usr/lib/udev/rules.d -name "*ptp*" -o -name "*ena*"

# View the rule
cat /etc/udev/rules.d/99-ptp-ena.rules  # or wherever it is
```

Expected rule format:
```
SUBSYSTEM=="ptp", ATTR{clock_name}=="ena-ptp", SYMLINK+="ptp_ena"
```

## Testing Checklist

- [ ] Get latest AL2023 AMI ID
- [ ] Launch test with latest AMI
- [ ] Check if `clock_device` is `/dev/ptp_ena` in results
- [ ] Verify services start successfully
- [ ] Check diagnostic output for symlink detection log
- [ ] Compare results with older AMI (if available)
- [ ] Verify crash detection still works correctly
- [ ] Check that recommendations are helpful

## What to Look For

### Success Indicators:
✅ `clock_device: "/dev/ptp_ena"` in results  
✅ Log message: "Using /dev/ptp_ena symlink"  
✅ `ptp4l_running: true`  
✅ `phc2sys_running: true`  
✅ `supported: true`  

### Potential Issues:
⚠️ Symlink not created after driver reload  
⚠️ Services configured for wrong device  
⚠️ udev rule not present in AMI  

## Additional Notes

- The tool already supports both scenarios (with/without symlink)
- The symlink is preferred but not required
- Fallback to `/dev/ptp0` still works correctly
- The improvement is purely for consistency and ease of configuration

---

**Date**: December 3, 2025  
**Ready for Testing**: Yes ✅
