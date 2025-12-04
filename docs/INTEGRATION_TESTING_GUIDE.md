# Integration Testing Guide for PTP Instance Tester

This document provides comprehensive end-to-end testing procedures for the new features added to the PTP Instance Tester:
- Placement Group Support (Task 12)
- Instance Quantity Specification (Task 13)
- Configuration File Support (Task 14)

## Prerequisites

Before running integration tests, ensure you have:

1. **AWS Account Access**
   - Valid AWS credentials configured (via profile or environment variables)
   - IAM permissions for EC2 operations (RunInstances, TerminateInstances, DescribeInstances, CreateTags)
   - IAM permissions for SSM (GetParameter) to retrieve latest AMIs
   - IAM permissions for placement groups (DescribePlacementGroups)

2. **AWS Resources**
   - A VPC with at least one subnet
   - An EC2 key pair for SSH access
   - The corresponding private key file with secure permissions (0600 or 0400)
   - A security group allowing SSH access (port 22)
   - (Optional) An existing placement group for placement group tests

3. **Local Environment**
   - Python 3.8 or later
   - PTP Instance Tester installed (`pip install -e .`)
   - PyYAML library installed (`pip install pyyaml`)

4. **Cost Awareness**
   - Integration tests will launch real EC2 instances
   - Instances will incur AWS charges
   - Tests should terminate instances automatically, but verify cleanup

## Test Environment Setup

### 1. Create Test Resources

```bash
# Set your AWS region
export AWS_REGION=us-east-1

# Create a placement group for testing (if you don't have one)
aws ec2 create-placement-group \
    --group-name ptp-test-cluster \
    --strategy cluster \
    --region $AWS_REGION

# Verify placement group was created
aws ec2 describe-placement-groups \
    --group-names ptp-test-cluster \
    --region $AWS_REGION
```

### 2. Gather Required Information

```bash
# List your subnets
aws ec2 describe-subnets --region $AWS_REGION

# List your key pairs
aws ec2 describe-key-pairs --region $AWS_REGION

# List your security groups
aws ec2 describe-security-groups --region $AWS_REGION

# List your placement groups
aws ec2 describe-placement-groups --region $AWS_REGION
```

Record the following for your tests:
- Subnet ID: `subnet-xxxxxxxxx`
- Key pair name: `your-key-name`
- Private key path: `/path/to/your-key.pem`
- Security group ID: `sg-xxxxxxxxx`
- Placement group name: `ptp-test-cluster`

---

## Task 15.1: Test Placement Group Feature End-to-End

**Requirements:** 11.1, 11.2, 11.3, 11.4

### Test 15.1.1: Valid Placement Group

**Objective:** Verify instances launch successfully into an existing placement group

**Steps:**

1. Launch a single instance with a valid placement group:

```bash
ptp-tester \
    --instance-types c7i.large \
    --subnet-id subnet-xxxxxxxxx \
    --key-name your-key-name \
    --private-key-path /path/to/your-key.pem \
    --security-group-id sg-xxxxxxxxx \
    --placement-group ptp-test-cluster \
    --region us-east-1
```

**Expected Results:**
- ✓ Tool validates placement group exists before launching
- ✓ Tool displays: "✓ Placement group 'ptp-test-cluster' is valid and available"
- ✓ Instance launches successfully
- ✓ Instance is placed in the specified placement group
- ✓ Report shows placement group information in instance details
- ✓ JSON export includes placement_group field

**Verification:**

```bash
# Check instance placement group via AWS CLI
aws ec2 describe-instances \
    --instance-ids i-xxxxxxxxx \
    --query 'Reservations[0].Instances[0].Placement.GroupName' \
    --region us-east-1
```

### Test 15.1.2: Invalid Placement Group

**Objective:** Verify validation catches non-existent placement groups

**Steps:**

1. Attempt to launch with a non-existent placement group:

```bash
ptp-tester \
    --instance-types c7i.large \
    --subnet-id subnet-xxxxxxxxx \
    --key-name your-key-name \
    --private-key-path /path/to/your-key.pem \
    --security-group-id sg-xxxxxxxxx \
    --placement-group nonexistent-pg \
    --region us-east-1
```

**Expected Results:**
- ✓ Tool validates placement group before launching instances
- ✓ Tool displays error: "✗ Placement group validation failed: Placement group 'nonexistent-pg' not found in region us-east-1"
- ✓ Tool exits without launching any instances
- ✓ Exit code is non-zero

### Test 15.1.3: No Placement Group (Backward Compatibility)

**Objective:** Verify tool works without placement group (backward compatible)

**Steps:**

1. Launch instance without specifying placement group:

```bash
ptp-tester \
    --instance-types c7i.large \
    --subnet-id subnet-xxxxxxxxx \
    --key-name your-key-name \
    --private-key-path /path/to/your-key.pem \
    --security-group-id sg-xxxxxxxxx \
    --region us-east-1
```

**Expected Results:**
- ✓ Tool launches instance successfully
- ✓ Tool displays: "Placement Group: (none - using default EC2 placement)"
- ✓ Instance launches without placement group
- ✓ Report shows placement_group as None or omitted
- ✓ JSON export either omits placement_group or shows null

---

## Task 15.2: Test Instance Quantity Feature End-to-End

**Requirements:** 12.1, 12.2, 12.3, 12.4

### Test 15.2.1: Multiple Quantities Per Instance Type

**Objective:** Verify tool launches and tests multiple instances per type

**Steps:**

1. Launch multiple instances with quantity notation:

```bash
ptp-tester \
    --instance-types c7i.large:2,m7i.xlarge:3 \
    --subnet-id subnet-xxxxxxxxx \
    --key-name your-key-name \
    --private-key-path /path/to/your-key.pem \
    --security-group-id sg-xxxxxxxxx \
    --region us-east-1
```

**Expected Results:**
- ✓ Tool displays: "Instance types: c7i.large:2, m7i.xlarge:3 (total: 5 instance(s))"
- ✓ Tool warns about testing 5 total instances
- ✓ Tool launches 2 c7i.large instances
- ✓ Tool launches 3 m7i.xlarge instances
- ✓ Each instance is tested independently
- ✓ Tool displays: "Testing c7i.large instance 1 of 2"
- ✓ Tool displays: "Testing c7i.large instance 2 of 2"
- ✓ Tool displays: "Testing m7i.xlarge instance 1 of 3"
- ✓ (etc.)
- ✓ Report shows individual results for each instance
- ✓ Summary aggregates results by instance type

### Test 15.2.2: Independent Instance Testing

**Objective:** Verify each instance is tested independently

**Steps:**

1. Launch multiple instances of the same type:

```bash
ptp-tester \
    --instance-types c7i.large:3 \
    --subnet-id subnet-xxxxxxxxx \
    --key-name your-key-name \
    --private-key-path /path/to/your-key.pem \
    --security-group-id sg-xxxxxxxxx \
    --region us-east-1
```

**Expected Results:**
- ✓ Tool launches 3 separate c7i.large instances
- ✓ Each instance gets a unique instance ID
- ✓ Each instance is configured independently
- ✓ Each instance is verified independently
- ✓ Report shows 3 separate test results
- ✓ If one instance fails, others continue testing

### Test 15.2.3: Backward Compatibility (Single Instances)

**Objective:** Verify tool works with single instances (no quantity specified)

**Steps:**

1. Launch instances without quantity notation:

```bash
ptp-tester \
    --instance-types c7i.large,m7i.xlarge \
    --subnet-id subnet-xxxxxxxxx \
    --key-name your-key-name \
    --private-key-path /path/to/your-key.pem \
    --security-group-id sg-xxxxxxxxx \
    --region us-east-1
```

**Expected Results:**
- ✓ Tool displays: "Instance types: c7i.large, m7i.xlarge (total: 2 instance(s))"
- ✓ Tool launches 1 c7i.large instance
- ✓ Tool launches 1 m7i.xlarge instance
- ✓ Behavior is identical to previous versions
- ✓ Report shows 2 test results

### Test 15.2.4: Result Aggregation

**Objective:** Verify reports correctly aggregate results by type

**Steps:**

1. Review the JSON output from Test 15.2.1:

```bash
cat ptp_test_results_*.json | jq '.[] | {instance_type, instance_id, ptp_supported: .ptp_status.supported}'
```

**Expected Results:**
- ✓ JSON contains 5 separate test results
- ✓ Each result has unique instance_id
- ✓ Results are grouped by instance_type in summary
- ✓ Summary shows success rate per instance type
- ✓ Example: "c7i.large: 2/2 supported, m7i.xlarge: 3/3 supported"

---

## Task 15.3: Test Config File Feature End-to-End

**Requirements:** 13.1, 13.2, 13.3

### Test 15.3.1: YAML Config File

**Objective:** Verify tool loads and uses YAML configuration files

**Steps:**

1. Create a test YAML config file:

```bash
cat > test-config.yaml << 'EOF'
instance_types:
  - type: c7i.large
    quantity: 2
subnet_id: subnet-xxxxxxxxx
key_name: your-key-name
private_key_path: /path/to/your-key.pem
security_group_id: sg-xxxxxxxxx
region: us-east-1
EOF
```

2. Run with YAML config:

```bash
ptp-tester --config test-config.yaml
```

**Expected Results:**
- ✓ Tool displays: "Loading configuration from: test-config.yaml"
- ✓ Tool displays: "✓ Configuration file loaded successfully"
- ✓ Tool displays all configuration parameters from file
- ✓ Tool launches 2 c7i.large instances
- ✓ All parameters from config file are used correctly

### Test 15.3.2: JSON Config File

**Objective:** Verify tool loads and uses JSON configuration files

**Steps:**

1. Create a test JSON config file:

```bash
cat > test-config.json << 'EOF'
{
  "instance_types": [
    {"type": "c7i.large", "quantity": 2}
  ],
  "subnet_id": "subnet-xxxxxxxxx",
  "key_name": "your-key-name",
  "private_key_path": "/path/to/your-key.pem",
  "security_group_id": "sg-xxxxxxxxx",
  "region": "us-east-1"
}
EOF
```

2. Run with JSON config:

```bash
ptp-tester --config test-config.json
```

**Expected Results:**
- ✓ Tool displays: "Loading configuration from: test-config.json"
- ✓ Tool displays: "✓ Configuration file loaded successfully"
- ✓ Tool displays all configuration parameters from file
- ✓ Tool launches 2 c7i.large instances
- ✓ All parameters from config file are used correctly

### Test 15.3.3: CLI Override Behavior

**Objective:** Verify CLI arguments override config file values

**Steps:**

1. Run with config file and CLI overrides:

```bash
ptp-tester \
    --config test-config.yaml \
    --instance-types m7i.xlarge:1 \
    --region us-west-2
```

**Expected Results:**
- ✓ Tool loads config file
- ✓ Tool displays: "Using instance_types from config file" (initially)
- ✓ CLI --instance-types overrides config file value
- ✓ CLI --region overrides config file value
- ✓ Other parameters (subnet_id, key_name, etc.) come from config file
- ✓ Tool launches 1 m7i.xlarge instance (not c7i.large from config)
- ✓ Tool uses us-west-2 region (not us-east-1 from config)

### Test 15.3.4: Invalid Config File Handling

**Objective:** Verify error handling for invalid config files

**Test 15.3.4a: Invalid YAML Syntax**

```bash
cat > invalid.yaml << 'EOF'
instance_types:
  - type: c7i.large
    quantity: 2
  invalid yaml syntax here [
subnet_id: subnet-xxxxxxxxx
EOF

ptp-tester --config invalid.yaml
```

**Expected Results:**
- ✓ Tool displays: "✗ Failed to load configuration file: YAML parsing error at line X, column Y"
- ✓ Error message includes line and column numbers
- ✓ Tool exits with non-zero exit code
- ✓ No instances are launched

**Test 15.3.4b: Invalid JSON Syntax**

```bash
cat > invalid.json << 'EOF'
{
  "instance_types": [
    {"type": "c7i.large", "quantity": 2}
  ],
  "subnet_id": "subnet-xxxxxxxxx",
  invalid json syntax
}
EOF

ptp-tester --config invalid.json
```

**Expected Results:**
- ✓ Tool displays: "✗ Failed to load configuration file: JSON parsing error at line X, column Y"
- ✓ Error message includes line and column numbers
- ✓ Tool exits with non-zero exit code
- ✓ No instances are launched

**Test 15.3.4c: Missing Required Fields**

```bash
cat > incomplete.yaml << 'EOF'
instance_types:
  - type: c7i.large
    quantity: 2
# Missing subnet_id, key_name, private_key_path
EOF

ptp-tester --config incomplete.yaml
```

**Expected Results:**
- ✓ Tool loads config file successfully
- ✓ Tool displays: "✗ Missing required parameters: --subnet-id, --key-name, --private-key-path"
- ✓ Tool exits with non-zero exit code
- ✓ No instances are launched

**Test 15.3.4d: Non-existent Config File**

```bash
ptp-tester --config nonexistent.yaml
```

**Expected Results:**
- ✓ Tool displays: "✗ Failed to load configuration file: Configuration file not found: nonexistent.yaml"
- ✓ Tool exits with non-zero exit code
- ✓ No instances are launched

---

## Task 15.4: Test Combined Feature Usage

**Requirements:** 11.1, 12.1, 13.1

### Test 15.4.1: Config File with Placement Group and Quantities

**Objective:** Verify all features work together via config file

**Steps:**

1. Create a comprehensive config file:

```bash
cat > comprehensive-config.yaml << 'EOF'
instance_types:
  - type: c7i.large
    quantity: 2
  - type: m7i.xlarge
    quantity: 1
subnet_id: subnet-xxxxxxxxx
key_name: your-key-name
private_key_path: /path/to/your-key.pem
security_group_id: sg-xxxxxxxxx
placement_group: ptp-test-cluster
region: us-east-1
EOF
```

2. Run with comprehensive config:

```bash
ptp-tester --config comprehensive-config.yaml
```

**Expected Results:**
- ✓ Tool loads all parameters from config file
- ✓ Tool validates placement group
- ✓ Tool displays: "✓ Placement group 'ptp-test-cluster' is valid and available"
- ✓ Tool launches 2 c7i.large instances into placement group
- ✓ Tool launches 1 m7i.xlarge instance into placement group
- ✓ All 3 instances are in the same placement group
- ✓ Each instance is tested independently
- ✓ Report shows placement group for all instances
- ✓ Summary aggregates results by instance type

**Verification:**

```bash
# Verify all instances are in the placement group
aws ec2 describe-instances \
    --filters "Name=placement-group-name,Values=ptp-test-cluster" \
    --query 'Reservations[].Instances[].[InstanceId,InstanceType,Placement.GroupName]' \
    --region us-east-1
```

### Test 15.4.2: Config File with CLI Overrides

**Objective:** Verify CLI overrides work with all features

**Steps:**

1. Run with config file and multiple CLI overrides:

```bash
ptp-tester \
    --config comprehensive-config.yaml \
    --instance-types r7i.2xlarge:2 \
    --placement-group different-pg \
    --region us-west-2
```

**Expected Results:**
- ✓ Tool loads config file
- ✓ CLI --instance-types overrides config (r7i.2xlarge:2 instead of c7i.large:2,m7i.xlarge:1)
- ✓ CLI --placement-group overrides config (different-pg instead of ptp-test-cluster)
- ✓ CLI --region overrides config (us-west-2 instead of us-east-1)
- ✓ Other parameters come from config file
- ✓ Tool validates placement group in us-west-2
- ✓ Tool launches 2 r7i.2xlarge instances into different-pg

### Test 15.4.3: All Features via CLI Only

**Objective:** Verify all features work together via CLI (no config file)

**Steps:**

1. Run with all features via CLI:

```bash
ptp-tester \
    --instance-types c7i.large:2,m7i.xlarge:1 \
    --subnet-id subnet-xxxxxxxxx \
    --key-name your-key-name \
    --private-key-path /path/to/your-key.pem \
    --security-group-id sg-xxxxxxxxx \
    --placement-group ptp-test-cluster \
    --region us-east-1
```

**Expected Results:**
- ✓ Tool validates placement group
- ✓ Tool launches 2 c7i.large instances into placement group
- ✓ Tool launches 1 m7i.xlarge instance into placement group
- ✓ All instances are tested independently
- ✓ Report shows placement group and quantities correctly
- ✓ Behavior is identical to config file approach

---

## Cleanup

After completing all tests, ensure all resources are cleaned up:

### 1. Verify No Instances Remain

```bash
# List all instances created by ptp-tester
aws ec2 describe-instances \
    --filters "Name=tag:ManagedBy,Values=ptp-instance-tester" \
    --query 'Reservations[].Instances[].[InstanceId,State.Name,InstanceType]' \
    --region us-east-1
```

### 2. Terminate Any Remaining Instances

```bash
# If any instances remain, terminate them
aws ec2 terminate-instances \
    --instance-ids i-xxxxxxxxx i-yyyyyyyyy \
    --region us-east-1
```

### 3. Delete Test Placement Group (Optional)

```bash
# Delete the test placement group if you created it
aws ec2 delete-placement-group \
    --group-name ptp-test-cluster \
    --region us-east-1
```

### 4. Clean Up Test Config Files

```bash
rm -f test-config.yaml test-config.json comprehensive-config.yaml
rm -f invalid.yaml invalid.json incomplete.yaml
```

---

## Test Results Summary

After completing all tests, document your results:

### Task 15.1: Placement Group Feature
- [ ] Test 15.1.1: Valid placement group - PASS/FAIL
- [ ] Test 15.1.2: Invalid placement group - PASS/FAIL
- [ ] Test 15.1.3: No placement group (backward compat) - PASS/FAIL

### Task 15.2: Instance Quantity Feature
- [ ] Test 15.2.1: Multiple quantities per type - PASS/FAIL
- [ ] Test 15.2.2: Independent instance testing - PASS/FAIL
- [ ] Test 15.2.3: Backward compatibility - PASS/FAIL
- [ ] Test 15.2.4: Result aggregation - PASS/FAIL

### Task 15.3: Config File Feature
- [ ] Test 15.3.1: YAML config file - PASS/FAIL
- [ ] Test 15.3.2: JSON config file - PASS/FAIL
- [ ] Test 15.3.3: CLI override behavior - PASS/FAIL
- [ ] Test 15.3.4a: Invalid YAML syntax - PASS/FAIL
- [ ] Test 15.3.4b: Invalid JSON syntax - PASS/FAIL
- [ ] Test 15.3.4c: Missing required fields - PASS/FAIL
- [ ] Test 15.3.4d: Non-existent config file - PASS/FAIL

### Task 15.4: Combined Feature Usage
- [ ] Test 15.4.1: Config with placement group and quantities - PASS/FAIL
- [ ] Test 15.4.2: Config with CLI overrides - PASS/FAIL
- [ ] Test 15.4.3: All features via CLI only - PASS/FAIL

---

## Troubleshooting

### Common Issues

**Issue:** "Placement group validation failed"
- **Solution:** Verify placement group exists in the correct region
- **Command:** `aws ec2 describe-placement-groups --region us-east-1`

**Issue:** "Insufficient capacity for instance type"
- **Solution:** Try a different availability zone or instance type
- **Note:** Placement groups can have capacity constraints

**Issue:** "PyYAML not installed"
- **Solution:** Install PyYAML: `pip install pyyaml`

**Issue:** "Private key file has permissive permissions"
- **Solution:** Fix permissions: `chmod 600 /path/to/your-key.pem`

**Issue:** "SSH connection timeout"
- **Solution:** Verify security group allows SSH (port 22) from your IP

**Issue:** "Instances not terminating"
- **Solution:** Manually terminate via AWS Console or CLI

---

## Notes

- All integration tests require real AWS resources and will incur costs
- Tests should be run in a non-production AWS account
- Always verify cleanup after tests to avoid unexpected charges
- Some tests may take 10-15 minutes per instance due to PTP configuration
- Network connectivity issues may cause SSH timeouts - retry if needed
- Placement group capacity constraints may cause launch failures - this is expected AWS behavior

---

## Reporting Issues

If any tests fail, document:
1. Test number and name
2. Expected behavior
3. Actual behavior
4. Error messages (full output)
5. AWS region and instance types used
6. Relevant log files (ptp_tester_*.log)

Submit issues to the project repository with this information.
