# PTP Instance Tester

A command-line tool that automates the process of discovering which EC2 instance types support AWS's nanosecond-precision hardware packet timestamping via PTP (Precision Time Protocol).

## Overview

The PTP Instance Tester deploys EC2 instances, configures PTP hardware clocks, verifies functionality, and manages cleanup based on test results. This tool helps engineers identify which instance types support PTP beyond the officially documented list.

### Supported Architectures

The tool supports testing on both **x86_64** and **ARM64 (Graviton)** architectures:

- **x86_64**: Intel and AMD-based instance types (c5n, c6i, c7i, c6a, c7a, m6i, m7i, r6i, r7i, etc.)
- **ARM64/Graviton**: AWS Graviton-based instance types (c6g, c7g, c6gn, c7gn, m6g, m7g, r6g, r7g, t4g, etc.)

The tool automatically detects the architecture based on the instance type and selects the appropriate Amazon Linux 2023 AMI for that architecture.

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd ptp-instance-tester

# Install dependencies (includes PyYAML for config file support)
pip install -e .

# For development (includes testing dependencies)
pip install -e ".[dev]"
```

**Dependencies**:
- `boto3`: AWS SDK for Python
- `paramiko`: SSH client library
- `click`: Command-line interface framework
- `pyyaml`: YAML parser for configuration files

All dependencies are automatically installed with `pip install -e .`

## Usage

### Configuration Files

The tool supports loading configuration from YAML or JSON files, making it easy to repeat tests and share configurations with your team.

#### Configuration File Format

Create a configuration file in YAML or JSON format with your test parameters:

**YAML Example** (`my-config.yaml`):
```yaml
instance_types:
  - type: c7i.large
    quantity: 2
  - type: m7i.xlarge
    quantity: 3

subnet_id: subnet-12345678
key_name: my-key-pair
private_key_path: ~/.ssh/my-key.pem

# Optional parameters
placement_group: my-cluster-pg
region: us-east-1
profile: production
ami_id: ami-1234567890abcdef0
security_group_id: sg-12345678
```

**JSON Example** (`my-config.json`):
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

See `config.example.yaml` and `config.example.json` for complete examples with all available options.

#### Using Configuration Files

Test using a configuration file:

```bash
ptp-tester --config my-config.yaml
```

Override specific parameters from the command line (CLI arguments take precedence):

```bash
# Use config file but override region and instance types
ptp-tester --config my-config.yaml \
           --region us-west-2 \
           --instance-types c7i.large:5
```

#### Configuration File Benefits

- **Repeatability**: Save test configurations for consistent testing
- **Team Sharing**: Share configuration files with team members
- **Version Control**: Track configuration changes in git
- **Complex Setups**: Manage complex configurations more easily than long CLI commands
- **Documentation**: Configuration files serve as documentation of test parameters

#### CLI Override Precedence

When both a configuration file and CLI arguments are provided:
1. Configuration file values are loaded first
2. CLI arguments override configuration file values
3. Missing required parameters result in a clear error message

Example:
```bash
# Config file has: region: us-east-1
# CLI specifies: --region us-west-2
# Result: Tests run in us-west-2 (CLI takes precedence)
ptp-tester --config my-config.yaml --region us-west-2
```

#### Configuration File Validation

The tool validates configuration files and provides clear error messages:

- **File Not Found**: Reports if the config file doesn't exist
- **Parse Errors**: Shows line and column numbers for YAML/JSON syntax errors
- **Missing Required Fields**: Lists which required parameters are missing
- **Invalid Values**: Validates parameter formats (subnet IDs, AMI IDs, etc.)

Example error output:
```
✗ Failed to load configuration file: YAML parsing error at line 5, column 3: 
  expected <block end>, but found '-'
```

### Basic Usage

Test a single x86_64 instance type:

```bash
ptp-tester --instance-types c7i.large \
           --subnet-id subnet-12345678 \
           --key-name my-ec2-keypair \
           --private-key-path ~/.ssh/my-key.pem
```

Test a single Graviton (ARM64) instance type:

```bash
ptp-tester --instance-types c7gn.large \
           --subnet-id subnet-12345678 \
           --key-name my-ec2-keypair \
           --private-key-path ~/.ssh/my-key.pem
```

### Advanced Usage

Test multiple x86_64 instance types with custom configuration:

```bash
ptp-tester --instance-types c7i.large,m7i.xlarge,r6i.2xlarge \
           --subnet-id subnet-1234567890abcdef0 \
           --key-name my-ec2-keypair \
           --private-key-path ~/.ssh/my-key.pem \
           --region us-east-1 \
           --profile production \
           --ami-id ami-1234567890abcdef0 \
           --security-group-id sg-1234567890abcdef0
```

Test multiple Graviton instance types:

```bash
ptp-tester --instance-types c6gn.large,c7gn.xlarge,m7g.2xlarge \
           --subnet-id subnet-1234567890abcdef0 \
           --key-name my-ec2-keypair \
           --private-key-path ~/.ssh/my-key.pem \
           --region us-east-1
```

Test mixed architectures (x86_64 and ARM64):

```bash
ptp-tester --instance-types c7i.large,c7gn.large \
           --subnet-id subnet-1234567890abcdef0 \
           --key-name my-ec2-keypair \
           --private-key-path ~/.ssh/my-key.pem
```

Test with a placement group:

```bash
ptp-tester --instance-types c7i.large,m7i.xlarge \
           --subnet-id subnet-1234567890abcdef0 \
           --key-name my-ec2-keypair \
           --private-key-path ~/.ssh/my-key.pem \
           --placement-group my-cluster-pg
```

### Instance Quantity Specification

You can specify the number of instances to launch for each instance type using the `type:quantity` notation:

Test multiple instances of the same type:

```bash
ptp-tester --instance-types c7i.large:2 \
           --subnet-id subnet-1234567890abcdef0 \
           --key-name my-ec2-keypair \
           --private-key-path ~/.ssh/my-key.pem
```

Test multiple instance types with different quantities:

```bash
ptp-tester --instance-types c7i.large:2,m7i.xlarge:3,r6i.2xlarge:1 \
           --subnet-id subnet-1234567890abcdef0 \
           --key-name my-ec2-keypair \
           --private-key-path ~/.ssh/my-key.pem
```

Mix instance types with and without quantity specifications (defaults to 1):

```bash
ptp-tester --instance-types c7i.large:2,m7i.xlarge,r6i.2xlarge:3 \
           --subnet-id subnet-1234567890abcdef0 \
           --key-name my-ec2-keypair \
           --private-key-path ~/.ssh/my-key.pem
```

**Key Points:**
- **Format**: `instance-type:quantity` (e.g., `c7i.large:2`)
- **Default**: If no quantity is specified, defaults to 1 instance
- **Independent Testing**: Each instance is tested independently
- **Error Resilience**: If one instance fails, testing continues with remaining instances
- **Quantity Validation**: Quantity must be a positive integer
- **Warning Threshold**: Testing more than 5 total instances will prompt for confirmation

**Use Cases:**
- **Consistency Verification**: Test multiple instances of the same type to verify PTP support is consistent
- **Placement Group Testing**: Launch multiple instances into a placement group to test network performance
- **Redundancy Testing**: Verify PTP functionality across multiple instances for high-availability setups

### Configuration File Parameter

- `--config`: Path to configuration file (YAML or JSON format)
  - Optional parameter that loads test configuration from a file
  - Supported formats: `.yaml`, `.yml`, `.json`
  - Command-line arguments override config file values
  - See `config.example.yaml` or `config.example.json` for format examples
  - Example: `--config my-test-config.yaml`

### Required Parameters

**Note**: Required parameters can be provided via command-line arguments, configuration file, or a combination of both.

- `--instance-types`: Comma-separated list of EC2 instance types to test with optional quantities
  - Format: `family.size` or `family.size:quantity` (e.g., `c7i.large`, `m7i.xlarge:2`)
  - Valid sizes: `nano`, `micro`, `small`, `medium`, `large`, `xlarge`, `2xlarge`, `4xlarge`, etc., `metal`
  - Quantity: Optional positive integer (defaults to 1 if not specified)
  - Examples: 
    - Single instances: `c7i.large,m7i.xlarge,r6i.2xlarge`
    - With quantities: `c7i.large:2,m7i.xlarge:3,r6i.2xlarge:1`
    - Mixed: `c7i.large:2,m7i.xlarge,r6i.2xlarge:3`
  - **Note**: Testing more than 3 instance types or 5 total instances will prompt for confirmation

- `--subnet-id`: AWS subnet ID where instances will be launched
  - Format: `subnet-[0-9a-f]{8,17}`
  - Example: `subnet-12345678` or `subnet-1234567890abcdef0`
  - The region will be derived from the subnet ID if not explicitly provided

- `--key-name`: EC2 key pair name for SSH access
  - Must be an existing EC2 key pair in your AWS account
  - Example: `my-ec2-keypair`

- `--private-key-path`: Path to private SSH key file
  - Must be a readable file
  - Recommended permissions: `0600` or `0400`
  - The tool will warn if permissions are too permissive
  - Example: `~/.ssh/my-key.pem`

### Optional Parameters

- `--region`: AWS region
  - Format: `region-direction-number` (e.g., `us-east-1`, `eu-west-2`)
  - If not provided, the region will be derived from the subnet ID
  - Example: `us-east-1`, `eu-west-2`, `ap-southeast-1`

- `--profile`: AWS profile name
  - Uses credentials from the specified AWS profile
  - If not provided, uses default AWS credential chain
  - Example: `production`, `development`

- `--ami-id`: AMI ID to use for instances
  - Format: `ami-[0-9a-f]{8,17}`
  - If not provided, uses the latest Amazon Linux 2023 AMI
  - Example: `ami-1234567890abcdef0`

- `--security-group-id`: Security group ID for SSH access
  - Format: `sg-[0-9a-f]{8,17}`
  - Must allow SSH (port 22) access
  - If not provided, the tool will determine an appropriate security group
  - Example: `sg-1234567890abcdef0`

- `--placement-group`: Placement group name for instance placement
  - Optional parameter to launch instances into an existing placement group
  - The placement group must exist in the target region and be in 'available' state
  - Supports cluster, partition, and spread placement strategies
  - Useful for testing PTP with specific placement strategies
  - Example: `my-cluster-pg`

### Parameter Validation

The CLI performs comprehensive validation on all parameters:

- **Instance Types**: Validates AWS instance type naming convention
- **Subnet ID**: Validates AWS subnet ID format
- **AMI ID**: Validates AWS AMI ID format (if provided)
- **Security Group ID**: Validates AWS security group ID format (if provided)
- **Region**: Validates AWS region format (if provided)
- **Private Key Path**: Validates file exists, is readable, and checks permissions

Invalid parameters will result in clear error messages explaining the expected format.

## Architecture Support and Auto-Detection

### How Architecture Detection Works

The tool automatically detects the architecture based on the instance type family:

1. **Instance Type Analysis**: When you specify an instance type (e.g., `c7gn.large`), the tool extracts the instance family (`c7gn`)
2. **Architecture Mapping**: The tool maps known Graviton families to ARM64 and other families to x86_64
3. **AMI Selection**: If no AMI is provided, the tool queries AWS Systems Manager for the appropriate Amazon Linux 2023 AMI:
   - **x86_64**: `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64`
   - **ARM64**: `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64`
4. **Runtime Verification**: After instance launch, the tool verifies the architecture by running `uname -m` on the instance

### Graviton Instance Types with PTP Support

The following Graviton (ARM64) instance families are known to support or potentially support PTP:

#### Network-Optimized Graviton Instances
- **c6gn**: Compute-optimized with enhanced networking (100 Gbps)
  - Example: `c6gn.large`, `c6gn.xlarge`, `c6gn.2xlarge`, `c6gn.4xlarge`, `c6gn.8xlarge`, `c6gn.12xlarge`, `c6gn.16xlarge`
- **c7gn**: 7th generation compute-optimized with enhanced networking (200 Gbps)
  - Example: `c7gn.large`, `c7gn.xlarge`, `c7gn.2xlarge`, `c7gn.4xlarge`, `c7gn.8xlarge`, `c7gn.12xlarge`, `c7gn.16xlarge`

#### General Purpose Graviton Instances
- **c6g**: 6th generation compute-optimized
- **c7g**: 7th generation compute-optimized
- **m6g**: 6th generation general purpose
- **m7g**: 7th generation general purpose
- **r6g**: 6th generation memory-optimized
- **r7g**: 7th generation memory-optimized
- **t4g**: Burstable performance

**Note**: PTP support on Graviton instances requires ENA driver version 2.10.0 or later, which is available on Amazon Linux 2023 and recent versions of Amazon Linux 2.

### Supported x86_64 Instance Types

Common x86_64 instance families that support or potentially support PTP:

#### Network-Optimized x86_64 Instances
- **c5n**: 5th generation compute-optimized with enhanced networking (100 Gbps)
- **c6i**: 6th generation Intel compute-optimized
- **c7i**: 7th generation Intel compute-optimized
- **c6a**: 6th generation AMD compute-optimized
- **c7a**: 7th generation AMD compute-optimized

#### General Purpose x86_64 Instances
- **m6i**: 6th generation Intel general purpose
- **m7i**: 7th generation Intel general purpose
- **r6i**: 6th generation Intel memory-optimized
- **r7i**: 7th generation Intel memory-optimized

### Architecture-Specific Considerations

#### Graviton (ARM64) Considerations
- **Package Availability**: All required PTP packages (chrony, linuxptp, ethtool) are available for ARM64 on Amazon Linux 2023
- **Driver Compilation**: The ENA driver compiles natively on ARM64 without modification
- **Performance**: Graviton instances offer excellent price-performance for PTP workloads
- **Compatibility**: The tool handles architecture differences transparently

#### x86_64 Considerations
- **Broader Support**: More instance families available
- **Legacy Compatibility**: Works with older Amazon Linux 2 versions
- **Well-Tested**: x86_64 PTP configuration is more widely documented

### Custom AMI Usage

If you provide a custom AMI using `--ami-id`, ensure it matches the architecture of your instance type:

```bash
# Correct: ARM64 AMI for Graviton instance
ptp-tester --instance-types c7gn.large \
           --ami-id ami-arm64-custom \
           --subnet-id subnet-12345678 \
           --key-name my-key \
           --private-key-path ~/.ssh/my-key.pem

# Incorrect: x86_64 AMI for Graviton instance (will fail)
ptp-tester --instance-types c7gn.large \
           --ami-id ami-x86-64-custom \
           --subnet-id subnet-12345678 \
           --key-name my-key \
           --private-key-path ~/.ssh/my-key.pem
```

The tool will detect architecture mismatches during instance launch and report the error.

### Testing Recommendations

1. **Start with Network-Optimized**: Test `c6gn` and `c7gn` for Graviton, `c5n` for x86_64
2. **Test Both Architectures**: Compare PTP performance between x86_64 and ARM64
3. **Use Latest AMIs**: Always use the latest Amazon Linux 2023 for best PTP support
4. **Check Region Availability**: Not all instance types are available in all regions

## AWS IAM Permissions

The tool requires the following minimum IAM permissions to function:

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

### IAM Policy Explanation

- **ec2:RunInstances**: Launch EC2 instances for testing
- **ec2:TerminateInstances**: Clean up instances after testing
- **ec2:DescribeInstances**: Query instance status and details
- **ec2:DescribeInstanceStatus**: Check instance health and state
- **ec2:DescribeSubnets**: Validate subnet configuration
- **ec2:DescribeSecurityGroups**: Validate security group configuration
- **ec2:CreateTags**: Tag instances with owner and purpose information
- **ssm:GetParameter**: Query AWS Systems Manager for latest AMI IDs

### Security Best Practices

1. **Use IAM Roles**: When running on EC2 or in CI/CD pipelines, use IAM roles instead of long-term credentials
2. **Principle of Least Privilege**: Only grant the permissions listed above
3. **Resource Tags**: The tool tags all created instances for accountability
4. **Temporary Credentials**: Use AWS STS temporary credentials when possible
5. **Credential Chain**: The tool follows standard AWS credential resolution (environment variables → credentials file → IAM role)

## Credential Management

The tool uses the standard AWS credential chain:

1. Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)
2. AWS credentials file (`~/.aws/credentials`)
3. IAM role (when running on EC2)

You can specify a profile using the `--profile` option:

```bash
ptp-tester --profile production ...
```

## SSH Key Security

- Private SSH keys should have restrictive permissions (0600 or 0400)
- The tool will warn if key permissions are overly permissive
- Never commit private keys to version control
- Private key contents are never logged or displayed

## Output and Reporting

### Console Output

The tool provides detailed console output including:
- Instance launch status
- Architecture detection (x86_64 or aarch64)
- ENA driver version and compatibility
- PTP configuration progress
- Hardware clock detection
- Synchronization status
- Test results summary

Example output:
```
Configuration:
  Instance types: c7gn.large:2, m7i.xlarge:3 (total: 5 instance(s))

Testing instance type 1/2: c7gn.large (quantity: 2)
Testing c7gn.large instance 1 of 2
Detected architecture: arm64
Launching instance...
Instance i-1234567890abcdef0 launched successfully
Detected runtime architecture: aarch64
Waiting for instance to be running...
Instance is running
Establishing SSH connection...
Checking ENA driver version...
ENA driver version: 2.10.0 (compatible)
Configuring PTP...
Hardware clock detected: /dev/ptp0
PTP synchronization: SUCCESS
Architecture: aarch64
Time offset: 45.2 ns

Testing c7gn.large instance 2 of 2
...

PTP INSTANCE TESTER - SUMMARY REPORT
======================================================================

Total Instances Tested: 5
PTP Supported: 5
PTP Unsupported: 0

Test Results by Instance Type:
----------------------------------------------------------------------

c7gn.large (tested: 2, supported: 2/2)
  Instance 1/2: ✓ SUPPORTED
    Instance ID: i-1234567890abcdef0
    Architecture: aarch64
    AZ: us-east-1a
    Duration: 285.5s
    Clock Device: /dev/ptp0

  Instance 2/2: ✓ SUPPORTED
    Instance ID: i-1234567890abcdef1
    Architecture: aarch64
    AZ: us-east-1a
    Duration: 290.2s
    Clock Device: /dev/ptp0

m7i.xlarge (tested: 3, supported: 3/3)
  Instance 1/3: ✓ SUPPORTED
    ...
```

### JSON Report Format

Test results are exported in JSON format including architecture and instance quantity information:

```json
{
  "test_summary": {
    "total_instances": 5,
    "ptp_supported": 5,
    "ptp_unsupported": 0,
    "test_duration_seconds": 1250.5,
    "instance_types_tested": 2
  },
  "results": [
    {
      "instance_type": "c7gn.large",
      "instance_index": 1,
      "total_instances_of_type": 2,
      "instance_id": "i-1234567890abcdef0",
      "architecture": "aarch64",
      "availability_zone": "us-east-1a",
      "subnet_id": "subnet-12345",
      "ptp_status": {
        "supported": true,
        "ena_driver_version": "2.10.0",
        "hardware_clock_present": true,
        "synchronized": true,
        "clock_device": "/dev/ptp0",
        "time_offset_ns": 45.2
      },
      "kept_running": true,
      "timestamp": "2025-12-03T10:30:00Z"
    },
    {
      "instance_type": "c7gn.large",
      "instance_index": 2,
      "total_instances_of_type": 2,
      "instance_id": "i-1234567890abcdef1",
      "architecture": "aarch64",
      "availability_zone": "us-east-1a",
      "subnet_id": "subnet-12345",
      "ptp_status": {
        "supported": true,
        "ena_driver_version": "2.10.0",
        "hardware_clock_present": true,
        "synchronized": true,
        "clock_device": "/dev/ptp0",
        "time_offset_ns": 42.8
      },
      "kept_running": true,
      "timestamp": "2025-12-03T10:35:00Z"
    },
    {
      "instance_type": "c7i.large",
      "instance_index": 1,
      "total_instances_of_type": 3,
      "instance_id": "i-0987654321fedcba0",
      "architecture": "x86_64",
      "availability_zone": "us-east-1a",
      "subnet_id": "subnet-12345",
      "ptp_status": {
        "supported": true,
        "ena_driver_version": "2.10.0",
        "hardware_clock_present": true,
        "synchronized": true,
        "clock_device": "/dev/ptp0",
        "time_offset_ns": 38.7
      },
      "kept_running": true,
      "timestamp": "2025-12-03T10:40:00Z"
    }
  ]
}
```

## Project Structure

```
ptp-instance-tester/
├── src/
│   └── ptp_tester/
│       ├── __init__.py
│       ├── cli.py
│       ├── aws_manager.py
│       ├── ssh_manager.py
│       ├── ptp_configurator.py
│       ├── test_orchestrator.py
│       ├── report_generator.py
│       └── models.py
├── tests/
│   ├── __init__.py
│   ├── test_aws_manager.py
│   ├── test_ssh_manager.py
│   ├── test_ptp_configurator.py
│   ├── test_test_orchestrator.py
│   └── test_report_generator.py
├── pyproject.toml
└── README.md
```

## Placement Group Support

### Overview

Placement groups control how instances are placed on underlying hardware to meet specific networking, availability, or performance requirements. The PTP Instance Tester supports launching instances into existing placement groups.

### Placement Group Strategies

AWS supports three placement group strategies:

1. **Cluster**: Packs instances close together inside an Availability Zone
   - Provides lowest latency and highest packet-per-second network performance
   - Recommended for PTP testing when network performance is critical
   - All instances must be in the same AZ

2. **Partition**: Spreads instances across logical partitions
   - Each partition has its own set of racks
   - Reduces correlated hardware failures
   - Supports up to 7 partitions per AZ

3. **Spread**: Strictly places instances on distinct underlying hardware
   - Reduces risk of simultaneous failures
   - Limited to 7 instances per AZ per group
   - Best for critical instances that must be isolated

### Using Placement Groups

#### Prerequisites

1. **Create Placement Group**: Create a placement group in your AWS account before running the tool
   ```bash
   aws ec2 create-placement-group \
       --group-name my-cluster-pg \
       --strategy cluster \
       --region us-east-1
   ```

2. **Verify Placement Group**: Ensure the placement group is in 'available' state
   ```bash
   aws ec2 describe-placement-groups \
       --group-names my-cluster-pg \
       --region us-east-1
   ```

#### Testing with Placement Groups

Specify the placement group using the `--placement-group` parameter:

```bash
ptp-tester --instance-types c7i.large,m7i.xlarge \
           --subnet-id subnet-12345678 \
           --key-name my-key \
           --private-key-path ~/.ssh/my-key.pem \
           --placement-group my-cluster-pg
```

The tool will:
1. Validate the placement group exists and is available
2. Launch all instances into the specified placement group
3. Include placement group information in test reports

#### Placement Group Requirements

- **Cluster Strategy**: Recommended for PTP testing (lowest latency)
  - All instances must be in the same AZ
  - Instance types should be from the same instance family for best results
  - Supports most instance types

- **Partition Strategy**: Useful for testing PTP across partitions
  - Supports up to 7 partitions per AZ
  - Instances can be in different partitions

- **Spread Strategy**: Limited use for PTP testing
  - Maximum 7 instances per AZ per group
  - May not provide the low-latency benefits needed for PTP

#### Validation and Error Handling

The tool validates placement groups before launching instances:

- **Placement Group Not Found**: Tool exits with error before launching instances
- **Placement Group Not Available**: Tool exits if placement group is in 'deleting' or other non-available state
- **Launch Failures**: If instance launch fails due to placement group constraints (e.g., capacity), the error is reported and testing continues with remaining instance types

#### Example Output with Placement Group

```
Configuration:
  Instance types: c7i.large, m7i.xlarge
  Subnet ID: subnet-12345678
  Placement Group: my-cluster-pg

Validating placement group 'my-cluster-pg'...
✓ Placement group 'my-cluster-pg' is valid and available

Starting PTP tests...

Instance Type: c7i.large
Instance ID: i-1234567890abcdef0
Placement Group: my-cluster-pg
PTP Supported: ✓ YES
```

### Best Practices for Placement Groups

1. **Use Cluster Strategy**: For PTP testing, cluster placement groups provide the best network performance
2. **Same Instance Family**: Use instances from the same family (e.g., all c7i) for consistent placement
3. **Pre-create Groups**: Create placement groups before running tests to avoid delays
4. **Monitor Capacity**: Cluster placement groups can experience capacity constraints
5. **Clean Up**: Delete unused placement groups to avoid hitting account limits

## Troubleshooting

### Placement Group Issues

#### Placement Group Not Found
**Problem**: Tool reports "Placement group not found"

**Solution**:
- Verify the placement group exists: `aws ec2 describe-placement-groups --group-names <name>`
- Ensure you're using the correct region
- Check the placement group name spelling

#### Placement Group Not Available
**Problem**: Tool reports "Placement group is not available"

**Solution**:
- Check placement group state: `aws ec2 describe-placement-groups --group-names <name>`
- Wait if the placement group is being created
- Delete and recreate if the placement group is stuck in a bad state

#### Insufficient Capacity in Placement Group
**Problem**: Instance launch fails with "InsufficientInstanceCapacity" error

**Solution**:
- Try a different instance type
- Try a different AZ by using a subnet in another AZ
- Wait and retry later (capacity constraints are often temporary)
- Consider using a partition or spread placement group instead of cluster

#### Instance Type Not Compatible
**Problem**: Instance launch fails with placement group compatibility error

**Solution**:
- Verify instance type supports the placement group strategy
- For cluster placement groups, use instances from the same family
- Check AWS documentation for instance type placement group support

### Architecture-Related Issues

#### AMI Architecture Mismatch
**Problem**: Instance fails to launch with "AMI architecture mismatch" error

**Solution**: 
- If using a custom AMI, ensure it matches the instance type architecture
- Graviton instances (c6g, c7g, c6gn, c7gn, etc.) require ARM64 AMIs
- Intel/AMD instances (c6i, c7i, c6a, c7a, etc.) require x86_64 AMIs
- Let the tool auto-select the AMI by omitting `--ami-id`

#### Unknown Instance Type
**Problem**: Tool defaults to x86_64 for an unknown instance type

**Solution**:
- Verify the instance type name is correct
- If it's a new Graviton instance family, the tool will default to x86_64
- Provide an ARM64 AMI explicitly using `--ami-id` for new Graviton types

#### Package Installation Fails on ARM64
**Problem**: Package installation fails on Graviton instances

**Solution**:
- Ensure you're using Amazon Linux 2023 (recommended) or recent Amazon Linux 2
- Older AMIs may not have ARM64 package repositories configured
- Check that the AMI has `yum` or `dnf` configured for ARM64 architecture

#### ENA Driver Compilation Fails
**Problem**: ENA driver compilation fails on ARM64

**Solution**:
- Ensure kernel headers are installed: `sudo yum install -y kernel-devel-$(uname -r)`
- Verify gcc and make are available: `sudo yum install -y gcc make`
- The ENA driver supports ARM64 natively, so compilation should work identically to x86_64

### General Troubleshooting

#### SSH Connection Timeout
**Problem**: Cannot establish SSH connection to instance

**Solution**:
- Verify security group allows SSH (port 22) from your IP
- Check that the subnet has internet connectivity (or NAT gateway for private subnets)
- Ensure the private key matches the key pair name
- Wait longer - some instances take time to initialize SSH

#### PTP Not Supported
**Problem**: Hardware clock not detected on instance

**Solution**:
- Verify the instance type supports enhanced networking
- Check ENA driver version is 2.10.0 or later
- Some instance types may not support PTP hardware timestamping
- Try network-optimized instance types (c5n, c6gn, c7gn)

#### Permission Denied Errors
**Problem**: AWS API calls fail with permission errors

**Solution**:
- Review the IAM permissions section above
- Ensure your AWS credentials have the required permissions
- Check that you're using the correct AWS profile with `--profile`

## Development

```bash
# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run property-based tests
pytest -v tests/

# Run tests for specific architecture support
pytest tests/test_aws_manager.py -k architecture
```

## Frequently Asked Questions

### Architecture and Graviton Support

**Q: Does the tool support AWS Graviton processors?**

A: Yes! The tool fully supports both x86_64 and ARM64 (Graviton) architectures. It automatically detects the architecture based on the instance type and selects the appropriate AMI.

**Q: Which Graviton instance types support PTP?**

A: Network-optimized Graviton instances like c6gn and c7gn are most likely to support PTP. The tool can test any Graviton instance type including c6g, c7g, m6g, m7g, r6g, r7g, and t4g families.

**Q: Can I test both x86_64 and Graviton instances in the same run?**

A: Yes! You can specify mixed architectures in the `--instance-types` parameter:
```bash
ptp-tester --instance-types c7i.large,c7gn.large --subnet-id subnet-12345 ...
```

**Q: How does the tool know which AMI to use for each architecture?**

A: The tool automatically queries AWS Systems Manager for the latest Amazon Linux 2023 AMI matching the detected architecture. You can also provide a custom AMI using `--ami-id`, but ensure it matches the instance type architecture.

**Q: What if I specify a Graviton instance type with an x86_64 AMI?**

A: The instance launch will fail with an architecture mismatch error. Always let the tool auto-select the AMI, or ensure your custom AMI matches the instance architecture.

**Q: Are there performance differences between x86_64 and Graviton for PTP?**

A: Both architectures support nanosecond-precision PTP timestamping. Graviton instances often provide better price-performance ratios. Use this tool to test and compare both architectures for your specific use case.

**Q: Does the ENA driver work the same on both architectures?**

A: Yes, the ENA driver version 2.10.0+ supports PTP on both x86_64 and ARM64. The tool handles any architecture-specific differences transparently.

### General Questions

**Q: How much does it cost to run tests?**

A: Costs depend on instance types and test duration. Each test typically takes 5-10 minutes. The tool automatically terminates instances without PTP support to minimize costs.

**Q: Can I keep instances running after tests?**

A: Yes! For instances with functional PTP, the tool prompts you to select which instances to keep running. Unselected instances are automatically terminated.

**Q: What regions are supported?**

A: All AWS regions are supported. Specify the region using `--region` or let the tool derive it from the subnet ID.

**Q: Can I test in a private subnet?**

A: Yes, but ensure the subnet has internet access via a NAT gateway for package installation and PTP synchronization.

## License

[Add your license here]

## Contributing

[Add contribution guidelines here]
