# Spec Update Summary - Service Debugging Requirements

## Date: 2025-12-03

## Problem Identified

The PTP Instance Tester successfully builds linuxptp from source and creates systemd service files, but the services crash immediately with exit code 255. The current implementation doesn't detect or diagnose these crashes, leading to false "not supported" results.

## Spec Updates Completed

### 1. Requirements Document Updates

Added two new requirements to `.kiro/specs/ptp-instance-tester/requirements.md`:

#### Requirement 9: Service Failure Detection
**User Story:** As a cloud engineer, I want the tool to detect and diagnose PTP service failures, so that I can understand why services are not running and take corrective action.

**Acceptance Criteria:**
1. Capture service status and error logs when services fail to start
2. Detect crash loops and report exit codes
3. Extract and report relevant error messages from service logs
4. Check for common failure causes (dependencies, configuration, permissions)
5. Verify binary permissions and library dependencies

#### Requirement 10: Actionable Recommendations
**User Story:** As a cloud engineer, I want the tool to provide actionable recommendations for service failures, so that I can fix issues without deep debugging.

**Acceptance Criteria:**
1. Provide specific recommendations based on failure type
2. Suggest configuration fixes for configuration errors
3. List missing dependencies when found
4. Recommend permission corrections for permission issues
5. Provide troubleshooting steps for hardware timestamping failures

### 2. Design Document Updates

Added four new correctness properties to `.kiro/specs/ptp-instance-tester/design.md`:

#### Property 17: Service crash detection
*For any* PTP service (ptp4l or phc2sys) that fails to start, the system should detect the crash state and capture the exit code.
**Validates: Requirements 9.1, 9.2**

#### Property 18: Service log capture
*For any* PTP service that is not running, the system should capture and include service logs in the diagnostic output.
**Validates: Requirements 9.3**

#### Property 19: Failure cause identification
*For any* service failure, the system should check for common failure causes including missing dependencies, configuration errors, and permission issues.
**Validates: Requirements 9.4, 9.5**

#### Property 20: Actionable recommendations
*For any* detected service failure, the system should provide specific recommendations based on the failure type.
**Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5**

## Root Cause Analysis

### Current Behavior

The `verify_ptp()` method in `ptp_configurator.py` only checks for "active (running)" status:

```python
ptp4l_running = "active (running)" in result.stdout.lower()
phc2sys_running = "active (running)" in result.stdout.lower()
```

This misses services in crash loops that show "activating (auto-restart)".

### What's Happening

From test results `ptp_test_results_20251203_030027.json`:

1. **Source build succeeds** - linuxptp v4.3 built and installed to `/usr/local/sbin`
2. **Service files created** - Both ptp4l.service and phc2sys.service created
3. **Services start but crash** - Exit code 255 (EXCEPTION)
4. **Systemd auto-restarts** - Services enter crash loop
5. **Verification fails** - Tool reports "not supported" because services aren't "active (running)"

### Exit Code 255 Causes

Exit code 255 typically indicates:
- Missing shared libraries (ldd shows "not found")
- Configuration file errors
- Permission issues
- Hardware access failures
- Incompatible binary

## Implementation Requirements

### 1. Enhanced Service Status Detection (HIGH PRIORITY)

```python
def check_service_status(self, ssh_manager, connection, service_name):
    """Check service status and detect crash loops."""
    result = ssh_manager.execute_command(
        connection,
        f"sudo systemctl status {service_name} 2>&1",
        timeout=30
    )
    
    return {
        'running': 'active (running)' in result.stdout.lower(),
        'failed': 'failed' in result.stdout.lower(),
        'crash_loop': 'activating (auto-restart)' in result.stdout.lower(),
        'exit_code': extract_exit_code(result.stdout)
    }
```

### 2. Service Log Capture (HIGH PRIORITY)

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

### 3. Binary Dependency Check (MEDIUM PRIORITY)

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

### 4. Manual Execution Test (MEDIUM PRIORITY)

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

When `verify_ptp()` finds services not running:

1. **Detect crash state** - Check for "activating (auto-restart)" and exit codes
2. **Capture service logs** - Get last 50 lines from journalctl for each service
3. **Check dependencies** - Run ldd on /usr/local/sbin/ptp4l and phc2sys
4. **Test manual execution** - Try running binaries with --help
5. **Verify permissions** - Check binary execute permissions (should be 755)
6. **Check device access** - Verify /dev/ptp0 is accessible (ls -la /dev/ptp*)
7. **Validate configuration** - Check /etc/ptp4l.conf exists and is readable
8. **Report findings** - Add all diagnostic info to PTPStatus.diagnostic_output

## Next Steps

### Immediate Actions

1. **Update `verify_ptp()` method** to detect crash loops
2. **Add service log capture** when services aren't running
3. **Implement dependency checking** for source-built binaries
4. **Add manual execution tests** before reporting failure

### Task List Updates

Add new tasks to `.kiro/specs/ptp-instance-tester/tasks.md`:

```markdown
- [ ] 11. Enhance service failure detection and debugging
- [ ] 11.1 Update verify_ptp() to detect service crash loops
  - Detect "activating (auto-restart)" status
  - Extract and report exit codes
  - _Requirements: 9.1, 9.2_

- [ ] 11.2 Add service log capture for failed services
  - Capture journalctl output for ptp4l and phc2sys
  - Include logs in diagnostic_output
  - _Requirements: 9.3_

- [ ] 11.3 Implement binary dependency checking
  - Run ldd on ptp4l and phc2sys binaries
  - Detect missing shared libraries
  - Report missing dependencies
  - _Requirements: 9.4, 9.5_

- [ ] 11.4 Add manual execution testing
  - Test binaries with --help before starting services
  - Verify binaries can execute
  - Report execution failures
  - _Requirements: 9.4_

- [ ] 11.5 Implement failure recommendations
  - Provide specific recommendations based on failure type
  - Suggest fixes for common issues
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

- [ ]* 11.6 Write property test for crash detection
  - **Property 17: Service crash detection**
  - **Validates: Requirements 9.1, 9.2**

- [ ]* 11.7 Write property test for log capture
  - **Property 18: Service log capture**
  - **Validates: Requirements 9.3**
```

## Expected Outcome

After implementing these enhancements:

1. **Accurate detection** - Services in crash loops will be detected immediately
2. **Detailed diagnostics** - Specific error messages and logs will be captured
3. **Root cause identification** - Missing dependencies and configuration errors will be found
4. **Actionable guidance** - Users will receive specific recommendations to fix issues
5. **Better success rate** - Issues can be fixed and retested, leading to more "supported: true" results

## Files Created

1. `SERVICE_CRASH_ANALYSIS.md` - Detailed technical analysis of the crash issue
2. `SPEC_UPDATE_SUMMARY.md` - This file, summarizing spec updates and next steps

## Files Modified

1. `.kiro/specs/ptp-instance-tester/requirements.md` - Added Requirements 9 and 10
2. `.kiro/specs/ptp-instance-tester/design.md` - Added Properties 17-20
