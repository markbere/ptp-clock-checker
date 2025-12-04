# Design Document

## Overview

The PTP Instance Tester is a command-line tool that automates the process of discovering which EC2 instance types support AWS's nanosecond-precision hardware packet timestamping via PTP (Precision Time Protocol). The tool deploys instances, configures PTP hardware clocks, verifies functionality, and manages cleanup based on test results.

The tool addresses the gap in AWS documentation where some instance families (like c7i) may have PTP support but are not officially listed. By automating the deployment, configuration, and verification process, engineers can efficiently test multiple instance types to build a comprehensive list of PTP-capable instances.

## Architecture

The system follows a pipeline architecture with distinct stages:

1. **Input Validation & Configuration** - Parse user inputs, validate AWS credentials and parameters
2. **Instance Deployment** - Launch EC2 instances with specified configurations
3. **PTP Configuration** - SSH into instances and execute PTP setup commands
4. **PTP Verification** - Check for hardware clock presence and PTP synchronization
5. **Result Reporting** - Generate structured reports of test outcomes
6. **Cleanup Management** - Terminate or preserve instances based on results and user choice

The tool will be implemented as a Python CLI application using:
- **boto3** for AWS API interactions
- **paramiko** for SSH connections and command execution
- **click** or **argparse** for CLI argument parsing
- **dataclasses** for structured data models

## Components and Interfaces

### CLI Interface

The main entry point accepts the following parameters:

```
ptp-tester --instance-types <type1:qty1,type2:qty2> \
           --subnet-id <subnet-id> \
           --key-name <ec2-key-pair-name> \
           --private-key-path <path-to-private-key> \
           [--region <region>] \
           [--profile <aws-profile>] \
           [--ami-id <ami-id>] \
           [--security-group-id <sg-id>] \
           [--placement-group <placement-group-name>] \
           [--config <config-file-path>]
```

**Parameter Notes**:
- **instance-types**: Comma-separated list of instance types with optional quantities using colon notation
  - Format: `type1:qty1,type2:qty2` or `type1,type2` (defaults to quantity 1)
  - Examples: `c7i.large:2,m7i.xlarge:3` or `c7i.large,m7i.xlarge`
- **subnet-id**: The subnet ID is sufficient for deployment as it's globally unique and AWS can derive the VPC and availability zone from it
- **placement-group**: Optional - name of an existing EC2 placement group (cluster, partition, or spread strategy)
  - If specified, all instances will be launched into this placement group
  - The placement group must exist in the same region and availability zone
  - Instance types must be compatible with the placement group strategy
- **config**: Optional - path to a YAML or JSON configuration file
  - Command-line arguments override configuration file values
  - Allows for repeatable test configurations and team sharing
- **region**: Optional - if not provided, the tool will extract the region from the subnet ID or use the default region from AWS credentials
- **profile**: Optional - if not provided, uses default AWS credential chain (environment variables, ~/.aws/credentials, IAM role)
- **AWS Account**: Implicitly determined from the AWS credentials being used (profile or default credentials)

**Configuration File Format**:

YAML example:
```yaml
instance_types:
  - type: c7i.large
    quantity: 2
  - type: m7i.xlarge
    quantity: 3
  - type: r7i.2xlarge
    quantity: 1
subnet_id: subnet-12345678
key_name: my-key-pair
private_key_path: ~/.ssh/my-key.pem
placement_group: my-cluster-pg  # optional
region: us-east-1  # optional
profile: production  # optional
ami_id: ami-1234567890abcdef0  # optional
security_group_id: sg-12345678  # optional
```

JSON example:
```json
{
  "instance_types": [
    {"type": "c7i.large", "quantity": 2},
    {"type": "m7i.xlarge", "quantity": 3}
  ],
  "subnet_id": "subnet-12345678",
  "key_name": "my-key-pair",
  "private_key_path": "~/.ssh/my-key.pem",
  "placement_group": "my-cluster-pg",
  "region": "us-east-1"
}
```

**Cleanup Behavior**:
After testing completes, the tool handles cleanup as follows:
1. **Unsupported instances**: Automatically terminated (no PTP support detected)
2. **PTP-functional instances**: User is prompted with options:
   - Enter 'all' to keep all PTP-functional instances
   - Enter 'none' to terminate all PTP-functional instances
   - Enter comma-separated numbers (e.g., '1,3,5-7') to keep only those specific instances

### Config Loader Component

Handles loading and parsing configuration files:

```python
class ConfigLoader:
    def load_config(self, config_path: str) -> TestConfig
    def validate_config(self, config: TestConfig) -> List[str]
    def merge_with_cli_args(self, config: TestConfig, cli_args: Dict) -> TestConfig
```

**Configuration Loading**:
- Supports both YAML and JSON formats (detected by file extension)
- Validates required fields and data types
- Provides clear error messages for parsing failures
- Command-line arguments take precedence over config file values

### AWS Manager Component

Responsible for all AWS API interactions:

```python
class AWSManager:
    def __init__(self, region: str, profile: Optional[str])
    def launch_instance(self, config: InstanceConfig) -> Instance
    def wait_for_running(self, instance_id: str) -> Instance
    def terminate_instance(self, instance_id: str) -> bool
    def get_instance_details(self, instance_id: str) -> InstanceDetails
    def verify_placement_group(self, placement_group_name: str) -> bool
    def get_placement_group_details(self, placement_group_name: str) -> PlacementGroupInfo
```

**Placement Group Support**:
- Verifies placement group exists before launching instances
- Validates instance type compatibility with placement group strategy
- Supports cluster, partition, and spread placement strategies
- Reports placement group details in test results

### SSH Manager Component

Handles SSH connections and command execution:

```python
class SSHManager:
    def __init__(self, private_key_path: str)
    def connect(self, host: str, username: str) -> Connection
    def execute_command(self, connection: Connection, command: str) -> CommandResult
    def disconnect(self, connection: Connection)
```

### PTP Configurator Component

Encapsulates PTP configuration logic based on AWS ENA PTP documentation:

```python
class PTPConfigurator:
    def check_ena_driver_version(self, ssh_manager: SSHManager, connection: Connection) -> Tuple[bool, str]
    def check_ptp_device(self, ssh_manager: SSHManager, connection: Connection) -> Tuple[bool, str]
    def create_ptp_ena_symlink(self, ssh_manager: SSHManager, connection: Connection) -> bool
    def configure_chrony_phc(self, ssh_manager: SSHManager, connection: Connection) -> bool
    def verify_ptp(self, ssh_manager: SSHManager, connection: Connection) -> PTPStatus
```

**AWS ENA PTP Architecture:**

AWS ENA PTP uses a **chrony-based architecture** where chrony directly reads from the PTP hardware clock, NOT the traditional ptp4l/phc2sys daemon approach:

```
Traditional PTP (NOT used by AWS):
PTP Grand Master → ptp4l → PHC → phc2sys → System Clock

AWS ENA PTP (Correct):
PTP Hardware Clock (/dev/ptp_ena) → chrony → System Clock
```

The configuration steps follow AWS ENA PTP documentation:

1. **Check ENA driver version** (must be 2.10.0 or later for PTP support)
2. **Verify PTP hardware clock device** exists (`/dev/ptp0`, `/dev/ptp1`, etc.)
3. **Create /dev/ptp_ena symlink** for consistent device naming:
   - Check if `/dev/ptp_ena` symlink already exists
   - If missing, add udev rule: `SUBSYSTEM=="ptp", ATTR{clock_name}=="ena-ptp-*", SYMLINK += "ptp_ena"`
   - Reload udev rules: `sudo udevadm control --reload-rules && udevadm trigger`
4. **Configure chrony to use PTP hardware clock**:
   - Edit `/etc/chrony.conf` and add: `refclock PHC /dev/ptp_ena poll 0 delay 0.000010 prefer`
   - Restart chrony: `sudo systemctl restart chronyd`
5. **Verify chrony is using PHC**:
   - Run `chronyc sources` and check for `#* PHC0` as the preferred time source
   - The `*` indicates the preferred source, `PHC0` corresponds to the PTP hardware clock

**Important Notes:**
- Do NOT use ptp4l or phc2sys services (these are for traditional PTP, not AWS ENA PTP)
- Do NOT attempt to enable hardware timestamping with ethtool (not required for chrony approach)
- The PTP hardware clock is automatically available when the ENA driver loads
- Latest Amazon Linux 2023 AMIs include the udev rule by default
- Service crash detection for ptp4l/phc2sys is NOT applicable to the chrony-based approach

### Test Orchestrator Component

Coordinates the testing workflow:

```python
class TestOrchestrator:
    def __init__(self, aws_manager: AWSManager, ssh_manager: SSHManager, 
                 ptp_configurator: PTPConfigurator)
    def test_instance_type(self, instance_type: str, config: TestConfig) -> TestResult
    def test_multiple_instances(self, instance_types: List[str], 
                                config: TestConfig) -> List[TestResult]
    def handle_cleanup(self, results: List[TestResult]) -> CleanupReport
```

### Report Generator Component

Creates structured output of test results:

```python
class ReportGenerator:
    def generate_instance_report(self, result: TestResult) -> str
    def generate_summary_report(self, results: List[TestResult]) -> str
    def export_json(self, results: List[TestResult], filepath: str)
```

## Data Models

### InstanceTypeSpec
```python
@dataclass
class InstanceTypeSpec:
    instance_type: str
    quantity: int = 1
```

### InstanceConfig
```python
@dataclass
class InstanceConfig:
    instance_type: str
    subnet_id: str
    key_name: str
    ami_id: Optional[str]
    security_group_ids: List[str]
    placement_group: Optional[str] = None
```

### PlacementGroupInfo
```python
@dataclass
class PlacementGroupInfo:
    name: str
    strategy: str  # cluster, partition, or spread
    state: str  # available, pending, deleting
    partition_count: Optional[int] = None  # for partition strategy
```

### TestConfig
```python
@dataclass
class TestConfig:
    instance_type_specs: List[InstanceTypeSpec]
    subnet_id: str
    key_name: str
    private_key_path: str
    region: Optional[str] = None
    profile: Optional[str] = None
    ami_id: Optional[str] = None
    security_group_id: Optional[str] = None
    placement_group: Optional[str] = None
```

### InstanceDetails
```python
@dataclass
class InstanceDetails:
    instance_id: str
    instance_type: str
    availability_zone: str
    subnet_id: str
    public_ip: Optional[str]
    private_ip: str
    state: str
    placement_group: Optional[str] = None
    architecture: Optional[str] = None
```

### PTPStatus
```python
@dataclass
class PTPStatus:
    supported: bool
    ena_driver_version: Optional[str]
    ena_driver_compatible: bool  # True if version >= 2.10.0
    hardware_clock_present: bool
    ptp_ena_symlink_present: bool
    chrony_using_phc: bool  # True if chrony sources shows PHC0 as preferred
    chrony_synchronized: bool
    clock_device: Optional[str]
    time_offset_ns: Optional[float]
    error_message: Optional[str]
    diagnostic_output: Dict[str, str]  # Contains output from chronyc sources, chronyc tracking, ls -l /dev/ptp*
```

### TestResult
```python
@dataclass
class TestResult:
    instance_details: InstanceDetails
    ptp_status: PTPStatus
    configuration_success: bool
    timestamp: datetime
    duration_seconds: float
```

### CommandResult
```python
@dataclass
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    success: bool
```


## Testing Approach

The PTP Instance Tester relies on manual integration testing rather than automated unit or property-based tests. This approach is appropriate because:

1. **Real AWS Resources Required**: Testing requires actual EC2 instances, placement groups, VPCs, and other AWS resources that incur costs
2. **Real Network Connectivity**: SSH connections, AWS API calls, and internet connectivity cannot be reliably mocked
3. **Time-Dependent Operations**: Instance launch (1-2 minutes), PTP configuration (5-10 minutes), and driver compilation require real time
4. **Real AWS Behavior**: Placement group constraints, instance type availability, network latency, and service quotas must be tested in real environments

### Integration Testing

A comprehensive integration testing guide is provided in `docs/INTEGRATION_TESTING_GUIDE.md` that covers:

- Placement group feature testing
- Instance quantity specification testing
- Configuration file support testing
- Combined feature testing
- Error handling validation
- Backward compatibility verification

The integration testing guide provides step-by-step procedures for manually testing all features in a real AWS environment.

## Security Considerations

The tool must follow AWS security best practices for credential and key management:

### IAM Policies and Roles

**Minimum Required IAM Permissions**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:RunInstances",
        "ec2:TerminateInstances",
        "ec2:DescribeInstances",
        "ec2:DescribeInstanceStatus",
        "ec2:DescribeSubnets",
        "ec2:DescribeSecurityGroups",
        "ec2:CreateTags"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter"
      ],
      "Resource": "arn:aws:ssm:*:*:parameter/aws/service/ami-amazon-linux-latest/*"
    }
  ]
}
```

**Security Best Practices**:
- Use IAM roles instead of long-term credentials when running on EC2 or in CI/CD pipelines
- Apply principle of least privilege - only grant permissions needed for testing
- Use resource tags to track instances created by the tool
- Consider using AWS Organizations SCPs to restrict instance types or regions if needed

### Credential Management

**AWS Credentials**:
- Never hardcode AWS credentials in the code
- Use standard AWS credential chain: environment variables → credentials file → IAM role
- Support AWS profiles for multi-account testing
- Validate credentials before attempting any AWS operations
- Use temporary credentials (STS) when possible
- Log credential source (profile name, role ARN) for audit purposes without exposing secrets

**SSH Key Management**:
- Never log or display private key contents
- Validate private key file permissions (should be 0600 or 0400)
- Warn users if private key has overly permissive permissions
- Support SSH agent for key management as an alternative to file-based keys
- Clear SSH keys from memory after use
- Never transmit private keys over the network

### Security Group Management

**Temporary Security Groups**:
- If creating temporary security groups, restrict SSH access to the user's current IP only
- Use `https://checkip.amazonaws.com` to determine user's public IP
- Clean up temporary security groups after testing
- Tag temporary resources with `ptp-tester:temporary=true` for tracking

**Existing Security Groups**:
- Validate that provided security group allows SSH (port 22) access
- Warn if security group allows SSH from 0.0.0.0/0 (overly permissive)

### Instance Security

**Instance Configuration**:
- Use IMDSv2 (Instance Metadata Service v2) for enhanced security
- Apply security group rules that restrict access to necessary ports only
- Tag instances with owner information for accountability
- Consider using Systems Manager Session Manager as an alternative to SSH (future enhancement)

### Data Protection

**Sensitive Data Handling**:
- Redact sensitive information from logs (IP addresses, instance IDs in public logs)
- Store test reports securely with appropriate file permissions
- Avoid including AWS account IDs in public reports
- Sanitize error messages to prevent information disclosure

### Audit and Compliance

**Logging and Monitoring**:
- Log all AWS API calls for audit purposes
- Include timestamps and user context in logs
- Log instance lifecycle events (launch, terminate)
- Consider integrating with AWS CloudTrail for centralized audit logging

## Error Handling

The system must handle various error conditions gracefully:

### AWS API Errors
- **Invalid credentials**: Detect and report before attempting instance launch
- **Insufficient permissions**: Report specific permission requirements
- **API throttling**: Implement exponential backoff for retries
- **Instance launch failures**: Capture and report AWS error messages
- **Resource limits**: Detect and report quota/limit issues

### SSH Connection Errors
- **Connection timeout**: Retry with exponential backoff up to 3 attempts
- **Authentication failure**: Report key mismatch or permission issues
- **Connection refused**: Wait for SSH service to be ready (up to 5 minutes)
- **Network unreachability**: Report security group or network configuration issues

### PTP Configuration Errors
- **Incompatible ENA driver version**: If driver version < 2.10.0, report the current version, mark PTP as unsupported, skip configuration steps, and proceed to cleanup
- **Package installation failure**: Capture package manager error output
- **Configuration file write failure**: Report permission or disk space issues
- **Service start failure**: Capture systemd/service error messages
- **Command execution timeout**: Report and continue with diagnostic capture

### Cleanup Errors
- **Termination failure**: Report instance ID and error, suggest manual cleanup
- **Partial cleanup**: Track which resources were successfully cleaned up
- **Permission errors**: Report specific IAM permission requirements

All errors should be logged with sufficient context for debugging and included in the final report.



## Implementation Notes

### ENA Driver Version Handling

The tool must ensure the ENA driver version is 2.10.0 or higher before attempting PTP configuration:

1. **Version Check**: Execute `modinfo ena | grep version` to get the current driver version
2. **Version Parsing**: Parse the version string (format: "2.10.0") and compare with minimum required version (2.10.0)
3. **Handle Incompatible Version**: If version < 2.10.0:
   - Mark PTP as unsupported
   - Set `ena_driver_compatible = False` in PTPStatus
   - Include driver version in error message
   - Skip all PTP configuration steps
   - Proceed to cleanup (instance will be auto-terminated)
4. **Proceed**: Once version >= 2.10.0 is confirmed, continue with chrony-based PTP configuration

**Note**: The tool does NOT attempt to upgrade the ENA driver. Driver upgrades require kernel module compilation and can be complex. Instead, the tool reports the incompatibility and marks the instance as unsupported. Users should use Amazon Linux 2023 AMIs which include ENA driver 2.10.0 or later by default.

This ensures all prerequisites are met before attempting PTP configuration.

### PTP Configuration Commands

Based on AWS ENA PTP documentation, the complete configuration sequence using the chrony-based approach is:

```bash
# 1. Check ENA driver version (must be 2.10.0 or later)
modinfo ena | grep version
# Expected output: version: 2.10.0 or higher

# 2. Verify PTP hardware clock device exists
ls -la /dev/ptp*
# Expected: /dev/ptp0 or similar (automatically created by ENA driver)

# 3. Check if /dev/ptp_ena symlink exists
ls -l /dev/ptp_ena
# If missing, create udev rule for consistent device naming

# 4. Create udev rule for /dev/ptp_ena symlink (if needed)
sudo tee /etc/udev/rules.d/99-ptp-ena.rules > /dev/null <<EOF
SUBSYSTEM=="ptp", ATTR{clock_name}=="ena-ptp-*", SYMLINK += "ptp_ena"
EOF

# 5. Reload udev rules
sudo udevadm control --reload-rules && sudo udevadm trigger

# 6. Verify symlink was created
ls -l /dev/ptp_ena
# Expected: /dev/ptp_ena -> ptp0 (or similar)

# 7. Install chrony (if not already installed)
sudo yum install -y chrony  # AL2023

# 8. Configure chrony to use PTP hardware clock
# Backup existing config
sudo cp /etc/chrony.conf /etc/chrony.conf.backup

# Add PHC refclock configuration
sudo tee -a /etc/chrony.conf > /dev/null <<EOF

# PTP Hardware Clock configuration
refclock PHC /dev/ptp_ena poll 0 delay 0.000010 prefer
EOF

# 9. Restart chrony service
sudo systemctl restart chronyd
sudo systemctl enable chronyd

# 10. Wait for chrony to synchronize (a few seconds)
sleep 5

# 11. Verify chrony is using PTP hardware clock
chronyc sources
# Expected output should show: #* PHC0
# The * indicates preferred source, PHC0 is the PTP hardware clock

# 12. Check chrony tracking for synchronization details
chronyc tracking
# Shows current time offset and synchronization status

# 13. Verify PTP device information
ls -la /dev/ptp*
# Shows all PTP devices and the ptp_ena symlink
```

**Key Differences from Traditional PTP:**
- NO ptp4l daemon (not used in AWS ENA PTP)
- NO phc2sys daemon (not used in AWS ENA PTP)
- NO hardware timestamping enablement via ethtool (automatic with ENA driver)
- Chrony directly reads from PTP hardware clock via PHC refclock
- Much simpler configuration with fewer moving parts

### Placement Group Handling

**Placement Group Validation**:
1. If placement group is specified, verify it exists using `describe_placement_groups` API
2. Extract placement group strategy (cluster, partition, spread) and state
3. Validate that the placement group is in 'available' state
4. For partition strategy, note the partition count for reporting

**Instance Type Compatibility**:
- Cluster placement groups: Most instance types supported, but must be same instance family
- Partition placement groups: Limited to 7 partitions per AZ, supports most instance types
- Spread placement groups: Maximum 7 instances per AZ, supports most instance types
- The tool will attempt to launch instances and report any placement group capacity errors

**Error Handling**:
- If placement group doesn't exist: Report error and exit before launching instances
- If placement group is in 'deleting' state: Report error and exit
- If instance launch fails due to placement group constraints: Report specific error and continue with remaining instances

### Instance Quantity Handling

**Launch Strategy**:
- For each instance type with quantity N, launch N instances sequentially
- Tag each instance with an index number (1 to N) for identification
- Use consistent naming: `ptp-test-{instance-type}-{index}-{timestamp}`

**Testing Strategy**:
- Test each instance independently in the order they were launched
- Track results per instance, not just per instance type
- Continue testing remaining instances even if one fails

**Reporting Strategy**:
- Individual reports: Show each instance with its index number
- Summary reports: Aggregate by instance type showing success rate (e.g., "c7i.large: 2/3 successful")
- Cleanup: Present instances grouped by type with index numbers for selection

### Configuration File Handling

**File Format Detection**:
- Detect format by file extension: `.yaml`, `.yml` for YAML; `.json` for JSON
- Use PyYAML for YAML parsing
- Use standard json module for JSON parsing

**Validation**:
- Check for required fields: `instance_types`, `subnet_id`, `key_name`, `private_key_path`
- Validate data types for each field
- Validate instance type format and quantity values (must be positive integers)
- Validate file paths exist for `private_key_path`

**Merging with CLI Arguments**:
- Load configuration file first
- Override with any CLI arguments provided
- Display effective configuration before starting tests
- Log which values came from config file vs CLI

**Error Messages**:
- YAML parsing errors: Include line number and column
- JSON parsing errors: Include character position
- Missing required fields: List all missing fields
- Invalid values: Specify which field and why it's invalid

### Instance Selection Strategy

For AMI selection when not specified by user:
- Use Amazon Linux 2023 as default (most recent with PTP support)
- Query AWS SSM Parameter Store for latest AL2023 AMI ID
- Fall back to user-specified AMI if provided

### Security Group Requirements

The tool should either:
1. Accept an existing security group ID from the user
2. Create a temporary security group allowing SSH (port 22) from the user's IP
3. Clean up temporary security groups after testing

### Timeout Values

- Instance launch wait: 5 minutes
- SSH connection attempts: 3 retries with 30-second intervals
- Command execution timeout: 2 minutes per command
- Instance termination wait: 2 minutes

### Output Format

JSON report structure with new features:
```json
{
  "test_summary": {
    "total_instances": 5,
    "ptp_supported": 4,
    "ptp_unsupported": 1,
    "test_duration_seconds": 650.5,
    "placement_group": "my-cluster-pg",
    "instance_type_summary": {
      "c7i.large": {"total": 2, "supported": 2, "unsupported": 0},
      "m7i.xlarge": {"total": 3, "supported": 2, "unsupported": 1}
    }
  },
  "results": [
    {
      "instance_id": "i-1234567890abcdef0",
      "instance_type": "c7i.large",
      "instance_index": 1,
      "availability_zone": "us-east-1a",
      "subnet_id": "subnet-12345",
      "placement_group": "my-cluster-pg",
      "ptp_status": {
        "supported": true,
        "hardware_clock_present": true,
        "synchronized": true,
        "clock_device": "eth0",
        "diagnostic_output": {...}
      },
      "kept_running": true,
      "timestamp": "2025-12-02T10:30:00Z"
    }
  ]
}
```
