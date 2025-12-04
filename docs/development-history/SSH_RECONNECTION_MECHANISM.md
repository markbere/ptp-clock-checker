# SSH Reconnection Mechanism for Driver Reload

## Problem

When enabling PHC (PTP Hardware Clock) on the ENA driver using the module parameter approach (`rmmod ena && modprobe ena enable_phc=1`), the network driver is reloaded, which **drops the active SSH connection** since SSH runs over the network interface managed by that driver.

## Symptoms

```
2025-12-03 00:46:37,797 - ptp_tester.ptp_configurator - INFO - Enabling PHC via module parameter...
[SSH connection drops]
[Test fails or hangs]
```

## Solution

Implemented automatic SSH reconnection mechanism that:
1. Detects when driver reload is needed
2. Uses background execution to survive connection drop
3. Waits for driver reload to complete
4. Automatically reconnects SSH
5. Continues with PTP configuration

## Implementation Details

### 1. Updated `enable_ena_phc()` Return Type

Changed from `bool` to `tuple[bool, bool]`:

```python
def enable_ena_phc(
    self,
    ssh_manager: SSHManager,
    connection: SSHClient,
    instance_ip: str
) -> tuple[bool, bool]:
    """
    Returns:
        Tuple of (success: bool, needs_reconnect: bool)
        - success: True if PHC enabled successfully
        - needs_reconnect: True if SSH connection was dropped
    """
```

### 2. Background Execution for Driver Reload

Uses `nohup` and background execution to ensure command completes even after SSH disconnects:

```python
# Use nohup and background execution to survive connection drop
result = ssh_manager.execute_command(
    connection,
    "nohup bash -c 'sleep 1 && sudo rmmod ena && sudo modprobe ena enable_phc=1' > /tmp/ena_phc_reload.log 2>&1 &",
    timeout=5
)

# Wait for driver reload to complete
logger.info("Waiting 10 seconds for driver reload to complete...")
time.sleep(10)

# Signal that reconnection is needed
return (True, True)  # Success, needs reconnect
```

### 3. Automatic Reconnection in Orchestrator

The test orchestrator handles reconnection automatically:

```python
# Enable PHC
phc_enabled, needs_reconnect = self.ptp_configurator.enable_ena_phc(
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
```

### 4. Updated `_configure_ptp()` Signature

Changed to return tuple and accept reconnection parameters:

```python
def _configure_ptp(
    self,
    connection,
    ssh_host: str,
    ssh_username: str
) -> tuple:
    """
    Returns:
        Tuple of (success: bool, connection: SSHClient)
        Returns updated connection (may be reconnected)
    """
```

All return statements updated to return `(bool, connection)` tuple.

## Execution Flow

### Without Reconnection (devlink approach - Linux 6.16+)
```
1. Enable PHC via devlink
2. Reload driver via devlink (connection stays alive)
3. Return (True, False) - no reconnect needed
4. Continue with PTP configuration
```

### With Reconnection (module parameter approach)
```
1. Enable PHC via module parameter
2. Execute: nohup bash -c 'rmmod ena && modprobe ena enable_phc=1' &
3. SSH connection drops (expected)
4. Wait 10 seconds for driver reload
5. Return (True, True) - reconnect needed
6. Orchestrator closes old connection
7. Orchestrator reconnects with retries
8. Continue with PTP configuration on new connection
```

## Benefits

1. **Resilient**: Handles connection drops gracefully
2. **Automatic**: No manual intervention required
3. **Transparent**: Continues seamlessly after reconnection
4. **Robust**: Uses retries and backoff for reconnection
5. **Logged**: Clear logging of reconnection process

## Testing

The mechanism should be tested on:
- Instances requiring module parameter approach (older kernels)
- Instances supporting devlink (Linux 6.16+)
- Various network conditions

## Timing Considerations

- **10 second wait**: Allows driver reload to complete
  - `rmmod ena`: ~1-2 seconds
  - `modprobe ena enable_phc=1`: ~2-3 seconds
  - Network interface initialization: ~3-5 seconds
  - Total: ~6-10 seconds

- **Reconnection retries**: 5 attempts with 5 second initial backoff
  - Provides up to 25 seconds for SSH to become available
  - Should be sufficient for most scenarios

## Alternative Approaches Considered

1. **Serial console**: Too complex, not available on all instances
2. **User data script**: Requires instance restart, not suitable for testing
3. **AWS Systems Manager**: Additional dependency, not always available
4. **Longer timeout**: Doesn't solve the dropped connection issue

## Files Modified

1. **src/ptp_tester/ptp_configurator.py**:
   - Updated `enable_ena_phc()` return type
   - Added background execution for driver reload
   - Added reconnection signaling

2. **src/ptp_tester/test_orchestrator.py**:
   - Updated `_configure_ptp()` signature
   - Added reconnection handling
   - Updated all return statements to return tuple
   - Pass connection through configuration flow

## Logging Output

Successful reconnection will show:
```
INFO - Enabling PHC via module parameter...
WARNING - ⚠️  Module reload will drop SSH connection! Reconnection will be attempted automatically.
INFO - Driver reload initiated, SSH connection will drop...
INFO - Waiting 10 seconds for driver reload to complete...
INFO - Driver reload complete, reconnection required
INFO - Reconnecting SSH after driver reload...
INFO - ✓ SSH reconnected successfully after driver reload
```

## Error Handling

If reconnection fails:
- Retries up to 5 times with exponential backoff
- Logs detailed error messages
- Returns failure status
- Test continues to gather diagnostics if possible

## Future Enhancements

1. **Verify reload success**: Check `/tmp/ena_phc_reload.log` after reconnection
2. **Adaptive timing**: Adjust wait time based on instance type
3. **Health check**: Verify network interface is up before continuing
4. **Fallback strategies**: Alternative reconnection methods if primary fails
