# Implementation Plan

- [x] 1. Set up project structure and dependencies
  - Create Python project with proper directory structure (src, tests, etc.)
  - Set up pyproject.toml or requirements.txt with dependencies: boto3, paramiko, click
  - Create main entry point script
  - Document minimum required IAM permissions in README
  - _Requirements: 7.1_

- [x] 2. Implement CLI interface and argument parsing
  - Create CLI using click with all required and optional parameters
  - Implement parameter validation (instance types, subnet ID format, file paths)
  - Add help text and usage examples
  - _Requirements: 1.1, 1.2, 7.2, 7.3, 7.5_

- [x] 3. Implement AWS Manager component
- [x] 3.1 Create AWSManager class with boto3 EC2 client initialization
  - Implement credential resolution (profile, default chain) following AWS SDK best practices
  - Never hardcode credentials - use environment variables, credentials file, or IAM roles
  - Log credential source (profile name, role ARN) without exposing secrets
  - Implement region extraction from subnet ID or use provided region
  - Add error handling for invalid credentials
  - Validate credentials before attempting AWS operations
  - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [x] 3.2 Implement instance launch functionality
  - Create launch_instance method with InstanceConfig parameter
  - Handle AMI selection (user-provided or query SSM for latest AL2023)
  - Handle security group configuration with validation
  - Enable IMDSv2 for enhanced instance metadata security
  - Tag instances with owner and purpose for accountability
  - Add error handling for launch failures
  - _Requirements: 1.1, 1.2, 1.3, 1.6_

- [x] 3.3 Implement instance state management
  - Create wait_for_running method with timeout
  - Implement get_instance_details method
  - Implement terminate_instance method with verification
  - _Requirements: 1.5, 5.5_

- [x] 4. Implement SSH Manager component
- [x] 4.1 Create SSHManager class with paramiko
  - Implement SSH connection with private key authentication
  - Validate private key file permissions (warn if not 0600 or 0400)
  - Never log or display private key contents
  - Clear SSH keys from memory after use
  - Add connection retry logic with exponential backoff
  - Implement execute_command method returning CommandResult
  - Add timeout handling for commands
  - _Requirements: 2.1, 7.5_

- [x] 5. Implement PTP Configurator component
- [x] 5.1 Create PTPConfigurator class
  - Implement check_ena_driver_version method
  - Parse version string and compare with 2.10.0
  - _Requirements: 2.2_

- [x] 5.2 Implement ENA driver upgrade functionality
  - Install build dependencies (kernel-devel, gcc, make)
  - Clone amzn-drivers repository
  - Build and install ENA driver
  - Reload driver module
  - Verify new version
  - _Requirements: 2.3, 2.4_

- [x] 5.3 Implement PTP package installation
  - Install chrony, linuxptp, ethtool packages
  - Handle package installation errors
  - _Requirements: 2.5_

- [x] 5.4 Implement hardware timestamping enablement
  - Execute ethtool --set-phc-hwts command
  - Verify hardware timestamping is enabled
  - _Requirements: 2.6_

- [x] 5.5 Implement chrony-based PTP configuration
  - Create /etc/chrony.conf with PTP hardware clock reference
  - Restart and enable chronyd service
  - Check for /dev/ptp* devices
  - Create /dev/ptp_ena symlink if needed
  - _Requirements: 2.6_

- [x] 5.6 Implement PTP verification
  - Execute chronyc verification commands
  - Parse output to determine synchronization status
  - Return PTPStatus with all diagnostic information
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 6. Implement Test Orchestrator component
- [x] 6.1 Create TestOrchestrator class
  - Coordinate AWS Manager, SSH Manager, and PTP Configurator
  - Implement test_instance_type method for single instance testing
  - Handle SSH connection establishment and retry logic
  - _Requirements: 1.5, 2.1_

- [x] 6.2 Implement multi-instance testing
  - Implement test_multiple_instances method
  - Add sequential execution logic
  - Implement error resilience (continue on failure)
  - Add warning for >3 instance types
  - _Requirements: 6.1, 6.2, 6.4_

- [x] 6.3 Implement cleanup management
  - Implement handle_cleanup method
  - Auto-terminate instances without PTP support
  - Display PTP-functional instances with details
  - Prompt user for instance selection
  - Terminate unselected instances
  - _Requirements: 5.1, 5.2, 5.4_

- [x] 7. Implement Report Generator component
- [x] 7.1 Create ReportGenerator class
  - Implement generate_instance_report method
  - Include all required fields (instance type, ID, status, verification details)
  - Include conditional fields (clock info if functional, diagnostics if not)
  - Sanitize sensitive information from reports (consider redacting full IP addresses)
  - _Requirements: 4.1, 4.2, 4.3_

- [x] 7.2 Implement summary report generation
  - Implement generate_summary_report method
  - Aggregate all test results
  - Include summary statistics
  - _Requirements: 4.4, 6.3_

- [x] 7.3 Implement JSON/YAML export
  - Implement export_json method
  - Ensure valid JSON structure matching schema
  - Add YAML export option
  - _Requirements: 4.5_

- [x] 8. Implement main application flow
- [x] 8.1 Wire all components together in main entry point
  - Parse CLI arguments
  - Initialize all components
  - Execute test workflow
  - Handle errors and generate reports
  - _Requirements: All_

- [x] 8.2 Add comprehensive error handling and security logging
  - Handle AWS API errors with specific messages
  - Handle SSH connection errors with retry logic
  - Handle PTP configuration errors with diagnostics
  - Handle cleanup errors with resource tracking
  - Log all AWS API calls for audit purposes with timestamps
  - Sanitize error messages to prevent information disclosure
  - _Requirements: 1.4, 2.4, 2.7, 5.6_

- [x] 9. Add Graviton (ARM64) Architecture Support
- [x] 9.1 Add architecture detection to PTPConfigurator
  - Create detect_architecture method in PTPConfigurator class
  - Execute `uname -m` command to get architecture
  - Return 'x86_64', 'aarch64', or 'unknown'
  - Add logging for detected architecture
  - _Requirements: 1.1, 7.1_

- [x] 9.2 Add instance type to architecture mapping in AWSManager
  - Create _get_instance_type_architecture method in AWSManager
  - Map Graviton instance families to 'arm64': c6gn, c7gn, c6g, c7g, m6g, m7g, r6g, r7g, t4g
  - Map x86_64 instance families to 'x86_64': c6i, c7i, c6a, c7a, m6i, m7i, r6i, r7i, c5n
  - Default to 'x86_64' for unknown instance types
  - Add logging for architecture determination
  - _Requirements: 1.1, 1.2_

- [x] 9.3 Update AMI selection to support both architectures
  - Modify get_latest_al2023_ami method to accept architecture parameter
  - Use SSM parameter: /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64
  - Use SSM parameter: /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64
  - Default to x86_64 for backward compatibility
  - Add logging for AMI selection by architecture
  - _Requirements: 1.1, 1.3_

- [x] 9.4 Integrate architecture detection into instance launch
  - Update launch_instance method to detect architecture from instance type
  - If no AMI provided, call get_latest_al2023_ami with detected architecture
  - Log architecture being used for instance launch
  - Ensure backward compatibility with existing code
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 9.5 Add architecture field to InstanceDetails model
  - Add architecture: Optional[str] field to InstanceDetails dataclass
  - Populate architecture field during instance launch
  - Include architecture in instance details logging
  - _Requirements: 4.1, 4.2_

- [x] 9.6 Include architecture in test results and reports
  - Update TestResult to include architecture from InstanceDetails
  - Add architecture field to JSON/YAML export
  - Display architecture in console output
  - Include architecture in summary reports
  - _Requirements: 4.1, 4.2, 4.5_

- [x] 9.7 Update documentation for Graviton support
  - Document supported architectures (x86_64 and ARM64/Graviton)
  - List Graviton instance types with PTP support (c6gn, c7gn)
  - Document architecture auto-detection behavior
  - Add examples for testing Graviton instances
  - Update README with architecture information
  - _Requirements: 4.1, 4.4_

- [x] 10. Add Placement Group Support
- [x] 10.1 Add placement group validation to AWSManager
  - Create validate_placement_group method in AWSManager
  - Check if placement group exists in the target region
  - Verify placement group strategy is 'cluster' (required for network performance)
  - Return validation result with error details if invalid
  - Add logging for placement group validation
  - _Requirements: 11.1, 11.2_

- [x] 10.2 Update CLI to accept placement group parameter
  - Add --placement-group optional parameter to CLI
  - Add help text explaining placement group usage
  - Pass placement group to TestOrchestrator
  - _Requirements: 11.1_

- [x] 10.3 Update InstanceConfig model to include placement group
  - Add placement_group: Optional[str] field to InstanceConfig dataclass
  - Update InstanceConfig initialization in TestOrchestrator
  - _Requirements: 11.1_

- [x] 10.4 Update instance launch to use placement group
  - Modify launch_instance method to include Placement parameter when placement_group is provided
  - Use boto3 Placement={'GroupName': placement_group} in run_instances call
  - Add error handling for placement group launch failures
  - Log placement group being used for instance launch
  - _Requirements: 11.1, 11.3_

- [x] 10.5 Update reports to include placement group information
  - Add placement_group field to InstanceDetails if used
  - Include placement group in JSON/YAML export
  - Display placement group in console output when present
  - _Requirements: 11.4_

- [x] 10.6 Update documentation for placement group support
  - Document --placement-group parameter usage
  - Explain placement group requirements (cluster strategy)
  - Add examples for using placement groups
  - Update README with placement group information
  - _Requirements: 11.1, 11.4_

- [x] 11. Add Instance Quantity Specification Support
- [x] 11.1 Create InstanceTypeSpec model
  - Create InstanceTypeSpec dataclass with instance_type and quantity fields
  - Add validation for quantity (must be positive integer)
  - Add __str__ method for display formatting
  - _Requirements: 12.1_

- [x] 11.2 Update CLI to parse instance type with quantity notation
  - Modify --instance-types parameter to accept "type:quantity" format
  - Parse each instance type specification into InstanceTypeSpec
  - Default quantity to 1 if not specified (backward compatible)
  - Validate quantity is positive integer
  - Add help text with examples: "c7i.large:2,m7i.xlarge:3"
  - _Requirements: 12.1_

- [x] 11.3 Update TestOrchestrator to handle multiple instances per type
  - Modify test_multiple_instances to iterate over quantity for each instance type
  - Launch instances sequentially for each type based on quantity
  - Track all instances separately in results
  - Add logging for instance number within type (e.g., "c7i.large instance 1 of 2")
  - _Requirements: 12.2, 12.3_

- [x] 11.4 Update reports to show instance quantities
  - Group results by instance type in summary
  - Show individual results for each instance
  - Display quantity tested for each type
  - Update JSON/YAML export to include instance index
  - _Requirements: 12.4_

- [ ] 11.5 Update documentation for instance quantity support
  - Document instance:quantity notation format
  - Add examples: "c7i.large:2,m7i.xlarge:3"
  - Explain independent testing per instance
  - Update README with quantity specification information
  - _Requirements: 12.1, 12.4_

- [x] 12. Add Configuration File Support
- [x] 12.1 Create TestConfig model
  - Create TestConfig dataclass with all CLI parameters as optional fields
  - Include: instance_types, subnet_id, key_name, key_path, region, ami_id, security_group_ids, placement_group
  - Add from_dict class method for loading from parsed config
  - Add validation method for required fields
  - _Requirements: 13.1_

- [x] 12.2 Create ConfigLoader component
  - Create ConfigLoader class with load_config method
  - Support YAML format using PyYAML library
  - Support JSON format using json module
  - Auto-detect format from file extension (.yaml, .yml, .json)
  - Return TestConfig object
  - Add comprehensive error handling for file not found, parse errors, invalid format
  - _Requirements: 13.1, 13.2_

- [x] 12.3 Update CLI to accept config file parameter
  - Add --config optional parameter to CLI
  - Add help text explaining config file usage and format
  - Load config file if provided using ConfigLoader
  - _Requirements: 13.1_

- [x] 12.4 Implement CLI parameter override precedence
  - Merge config file values with CLI arguments
  - CLI arguments override config file values
  - Use config file values as defaults when CLI args not provided
  - Validate final merged configuration
  - Add logging showing which values came from config vs CLI
  - _Requirements: 13.3_

- [x] 12.5 Add PyYAML dependency
  - Add pyyaml to pyproject.toml dependencies
  - Update requirements documentation
  - _Requirements: 13.2_

- [x] 12.6 Update documentation for config file usage
  - Document config file format (YAML and JSON)
  - Reference example config files (config.example.yaml, config.example.json)
  - Document CLI override behavior
  - Add usage examples with config files
  - Update README with config file information
  - _Requirements: 13.1, 13.3_

- [x] 13. Integration and Testing
- [x] 13.1 Test placement group feature end-to-end
  - Manually test with existing placement group
  - Verify validation catches invalid placement groups
  - Verify instances launch into placement group correctly
  - Verify reports show placement group information
  - _Requirements: 11.1, 11.2, 11.3, 11.4_

- [x] 13.2 Test instance quantity feature end-to-end
  - Test with multiple quantities per instance type
  - Verify each instance is tested independently
  - Verify reports correctly aggregate results by type
  - Test backward compatibility with single instances
  - _Requirements: 12.1, 12.2, 12.3, 12.4_

- [x] 13.3 Test config file feature end-to-end
  - Test with YAML config file
  - Test with JSON config file
  - Test CLI override behavior
  - Test error handling for invalid config files
  - Verify all config parameters work correctly
  - _Requirements: 13.1, 13.2, 13.3_

- [x] 13.4 Test combined feature usage
  - Test using config file with placement group and quantities
  - Test CLI overrides with config file
  - Verify all features work together correctly
  - _Requirements: 11.1, 12.1, 13.1_

- [x] 14. Final implementation complete
  - All core features implemented and tested
  - Integration testing guide provided in docs/INTEGRATION_TESTING_GUIDE.md
  - Application ready for production use
