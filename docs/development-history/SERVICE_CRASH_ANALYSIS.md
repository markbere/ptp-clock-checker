# PTP Service Crash Analysis

## Date: 2025-12-03

## Problem Summary

PTP services (ptp4l and phc2sys) are crashing immediately after startup with exit code 255, preventing PTP functionality from working.

## Symptoms

From test results `ptp_test_results_20251203_030027.json`:

```
Process: 40430 ExecStart=/usr/local/sbin/ptp4l -f /etc/ptp4l.conf (code=exited, status=255/EXCEPTION)
Process: 40431 ExecStart=/usr/local/sbin/phc2sys -s /dev/ptp0 -c CLOCK_REALTIME -w -m -R 8 (code=exited, status=255/EXCEPTION)
```

Both services show:
- Status: `activating (auto-restart)` (crash loop)
- Exit code: 255 (EXCEPTION)
- Result: `exit-code`

## Root Cause Analysis

### Issue 1: Service Status Detection Gap

The `verify_ptp()` method only checks for "active (running)" status:

```python
ptp4l_running = "active (running)" in result.stdout.lower()
phc2sys_running = "active (running)" in result.stdout.lower()
```

**Problem:** This doesn't detect crash loops where services show "activating (auto-restart)".

### Issue 2: Missing Service Log Analysis

When services fail, the tool doesn't:
1. Capture service logs (`journalctl -u ptp4l -n 50`)
2. Check for specific error messages
3. Verify binary dependencies
4. Test binary execution manually

### Issue 3: No Failure Recovery

The configuration phase completes successfully (builds from source, creates service files), but when services crash, there's no:
1. Automatic retry with different configurations
2. Dependency verification
3. Manual execution test
4. Detailed error reporting

## Common Causes of Exit Code 255

Exit code 255 typically indicates:

1. **Missing shared libraries** - Binary can't find required .so files
2. **Configuration errors** - Invalid config file syntax
3. **Permission issues** - Can't access required files/devices
4. **Hardware access failures** - Can't open /dev/ptp0 or network interface
5. **Incompatible binary** - Built for wrong architecture or kernel

## Required Fixes

### 1. Enhanced Service Status Detection

```python
def check_service_status(self, ssh_manager, connection, service_name):
    """Check service status and detect crash loops."""
    result = ssh_manager.execute_command(
        connection,
        f"sudo systemctl status {service_name} 2>&1",
        timeout=30
    )
    
    status = {
        'running': 'active (running)' in result.stdout.lower(),
        'failed': 'failed' in result.stdout.lower(),
        'crash_loop': 'activating (auto-restart)' in result.stdout.lower(),
        'exit_code': None
    }
    
    # Extract exit code if present
    exit_match = re.search(r'code=exited, status=(\d+)', result.stdout)
    if exit_match:
        status['exit_code'] = int(exit_match.group(1))
    
    return status
```

### 2. Service Log Capture

```python
def get_service_logs(self, ssh_manager, connection, service_name, lines=50):
    """Get recent service logs for debugging."""
    result = ssh_manager.execute_command(
        connection,
        f"sudo journalctl -u {service_name} -n {lines} --no-pager",
        timeout=30
    )
    return result.stdout
```

### 3. Binary Dependency Check

```python
def check_binary_dependencies(self, ssh_manager, connection, binary_path):
    """Check if binary has all required shared libraries."""
    result = ssh_manager.execute_command(
        connection,
        f"ldd {binary_path}",
        timeout=30
    )
    
    missing_libs = []
    if 'not found' in result.stdout:
        for line in result.stdout.split('\n'):
            if 'not found' in line:
                missing_libs.append(line.strip())
    
    return missing_libs
```

### 4. Manual Execution Test

```python
def test_binary_execution(self, ssh_manager, connection, command):
    """Test if binary can execute manually."""
    result = ssh_manager.execute_command(
        connection,
        f"sudo {command} --help 2>&1",
        timeout=10
    )
    
    return {
        'success': result.exit_code == 0,
        'output': result.stdout,
        'error': result.stderr
    }
```

## Diagnostic Workflow

When services fail to start:

1. **Detect crash state** - Check for "activating (auto-restart)" and exit codes
2. **Capture service logs** - Get last 50 lines from journalctl
3. **Check dependencies** - Run ldd on binaries
4. **Test manual execution** - Try running binaries with --help
5. **Verify permissions** - Check binary execute permissions
6. **Check device access** - Verify /dev/ptp0 is accessible
7. **Validate configuration** - Check /etc/ptp4l.conf syntax
8. **Report findings** - Provide specific error messages and recommendations

## Implementation Priority

1. **HIGH**: Add crash loop detection to verify_ptp()
2. **HIGH**: Capture service logs when services aren't running
3. **MEDIUM**: Add binary dependency checking
4. **MEDIUM**: Add manual execution testing
5. **LOW**: Add automatic retry with different configurations

## Expected Outcome

After implementing these fixes:
- Services in crash loops will be detected immediately
- Specific error messages will be captured and reported
- Missing dependencies will be identified
- Configuration errors will be caught
- Users will receive actionable recommendations

## Next Steps

1. Update `verify_ptp()` to detect crash loops
2. Add service log capture to diagnostic output
3. Implement dependency checking for source-built binaries
4. Add manual execution tests before starting services
5. Update requirements and design documents with new acceptance criteria
