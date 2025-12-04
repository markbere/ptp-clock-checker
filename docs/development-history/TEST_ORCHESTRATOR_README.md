# TestOrchestrator Component

The TestOrchestrator is the central coordination component that orchestrates the complete PTP testing workflow.

## Overview

The TestOrchestrator coordinates three main components:
- **AWSManager**: Handles EC2 instance lifecycle (launch, monitor, terminate)
- **SSHManager**: Manages SSH connections and command execution
- **PTPConfigurator**: Configures and verifies PTP on instances

## Key Features

### 1. Single Instance Testing
Tests PTP support on a single EC2 instance type with complete workflow:
- Launch instance
- Wait for running state
- Establish SSH connection with retry logic
- Configure PTP (check/upgrade ENA driver, install packages, configure services)
- Verify PTP functionality
- Return comprehensive test results

### 2. Multi-Instance Testing
Tests multiple instance types sequentially with:
- Sequential execution (one instance at a time)
- Error resilience (continues testing even if one fails)
- Warning for large test batches (>3 instance types)
- Comprehensive results for all tested instances

### 3. Cleanup Management
Intelligent cleanup based on test results:
- Auto-terminates instances without PTP support
- Displays PTP-functional instances with full details
- Supports user selection of instances to keep
- Verifies termination completion
- Reports cleanup status and any failures

## Usage

### Basic Usage

```python
from ptp_tester import (
    AWSManager,
    SSHManager,
    PTPConfigurator,
    TestOrchestrator
)

# Initialize components
aws_manager = AWSManager(region='us-east-1', profile='my-profile')
ssh_manager = SSHManager(private_key_path='/path/to/key.pem')
ptp_configurator = PTPConfigurator()

# Create orchestrator
orchestrator = TestOrchestrator(
    aws_manager=aws_manager,
    ssh_manager=ssh_manager,
    ptp_configurator=ptp_configurator
)

# Test a single instance type
result = orchestrator.test_instance_type(
    instance_type='c7i.large',
    subnet_id='subnet-12345678',
    key_name='my-key'
)

print(f"PTP Supported: {result.ptp_status.supported}")
```

### Multi-Instance Testing

```python
# Test multiple instance types
results = orchestrator.test_multiple_instances(
    instance_types=['c7i.large', 'm7i.xlarge', 'r6i.2xlarge'],
    subnet_id='subnet-12345678',
    key_name='my-key',
    security_group_ids=['sg-12345678']
)

# Display results
for result in results:
    print(f"{result.instance_details.instance_type}: "
          f"PTP {'Supported' if result.ptp_status.supported else 'Not Supported'}")
```

### Cleanup Management

```python
# Handle cleanup
cleanup_report = orchestrator.handle_cleanup(
    results=results,
    auto_terminate_unsupported=True,
    prompt_for_selection=False
)

print(f"Terminated: {len(cleanup_report['terminated'])} instances")
print(f"Kept: {len(cleanup_report['kept'])} instances")
```

## Integration Testing

Use the provided integration test script to test on actual EC2 instances:

```bash
python test_orchestrator_integration.py \
    --instance-types c7i.large,m7i.xlarge \
    --subnet-id subnet-xxxxx \
    --key-name your-key-name \
    --private-key-path /path/to/key.pem \
    --region us-east-1 \
    --security-group-ids sg-xxxxx
```

## Property-Based Tests

The TestOrchestrator includes comprehensive property-based tests that verify:

1. **Property 11: Sequential test execution** - Tests execute in order
2. **Property 12: Test resilience** - Testing continues after failures
3. **Property 8: Automatic cleanup** - Unsupported instances are terminated
4. **Property 9: Selective cleanup** - User-selected instances are preserved
5. **Property 16: PTP-functional instance display** - All required fields are shown

Run property tests with:

```bash
python run_orchestrator_property_tests.py
```

## Error Handling

The TestOrchestrator handles various error conditions:

- **Instance launch failures**: Reports error and continues with remaining instances
- **SSH connection failures**: Retries with exponential backoff
- **PTP configuration failures**: Captures diagnostics and marks as unsupported
- **Cleanup failures**: Reports failed terminations for manual cleanup

## Requirements Validation

The TestOrchestrator validates the following requirements:

- **1.5**: Waits for instance to reach running state before SSH
- **2.1**: Establishes SSH connection after instance is running
- **5.1**: Auto-terminates instances without PTP support
- **5.2**: Displays PTP-functional instances with required details
- **5.4**: Preserves user-selected instances during cleanup
- **5.5**: Verifies termination completion
- **6.1**: Tests instance types sequentially
- **6.2**: Continues testing after individual failures
- **6.4**: Warns when testing >3 instance types

## Architecture

```
TestOrchestrator
├── test_instance_type()      # Single instance workflow
│   ├── Launch instance
│   ├── Wait for running
│   ├── Connect SSH (with retry)
│   ├── Configure PTP
│   └── Verify PTP
│
├── test_multiple_instances()  # Multi-instance workflow
│   ├── Warn if >3 instances
│   ├── Test each sequentially
│   └── Continue on failures
│
└── handle_cleanup()           # Cleanup management
    ├── Auto-terminate unsupported
    ├── Display PTP-functional
    ├── Prompt for selection
    └── Terminate unselected
```

## Next Steps

After implementing the TestOrchestrator, the next components to implement are:

1. **Report Generator** - Generate structured reports (JSON/YAML)
2. **CLI Integration** - Wire TestOrchestrator into the CLI
3. **Main Application Flow** - Complete end-to-end workflow
