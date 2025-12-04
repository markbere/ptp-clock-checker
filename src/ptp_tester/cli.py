"""Command-line interface for PTP Instance Tester."""

import os
import re
import sys
from pathlib import Path
from typing import List

import click


def validate_instance_types(ctx, param, value):
    """Validate instance type format with optional quantity and warn for large lists.
    
    Instance types should follow AWS naming convention: family.size
    Quantity can be specified with colon notation: family.size:quantity
    Examples: c7i.large, m7i.xlarge:2, r6i.2xlarge:3
    """
    from ptp_tester.models import InstanceTypeSpec
    
    if not value:
        raise click.BadParameter("At least one instance type must be provided")
    
    # Split by comma and strip whitespace
    instance_type_specs_raw = [t.strip() for t in value.split(',') if t.strip()]
    
    if not instance_type_specs_raw:
        raise click.BadParameter("At least one instance type must be provided")
    
    # AWS instance type pattern: family.size (e.g., c7i.large, m7i.xlarge)
    instance_type_pattern = re.compile(r'^[a-z][0-9][a-z]*\.(nano|micro|small|medium|large|xlarge|[0-9]+xlarge|metal)$')
    
    # Parse each spec into InstanceTypeSpec objects
    instance_type_specs = []
    invalid_specs = []
    
    for spec_str in instance_type_specs_raw:
        # Check if quantity is specified with colon notation
        if ':' in spec_str:
            parts = spec_str.split(':')
            if len(parts) != 2:
                invalid_specs.append(f"{spec_str} (invalid format)")
                continue
            
            instance_type, quantity_str = parts
            instance_type = instance_type.strip()
            quantity_str = quantity_str.strip()
            
            # Validate instance type format
            if not instance_type_pattern.match(instance_type):
                invalid_specs.append(f"{instance_type} (invalid instance type)")
                continue
            
            # Validate and parse quantity
            try:
                quantity = int(quantity_str)
                if quantity < 1:
                    invalid_specs.append(f"{spec_str} (quantity must be positive)")
                    continue
            except ValueError:
                invalid_specs.append(f"{spec_str} (quantity must be an integer)")
                continue
            
            # Create InstanceTypeSpec
            try:
                spec = InstanceTypeSpec(instance_type=instance_type, quantity=quantity)
                instance_type_specs.append(spec)
            except ValueError as e:
                invalid_specs.append(f"{spec_str} ({str(e)})")
        else:
            # No quantity specified, default to 1
            instance_type = spec_str.strip()
            
            # Validate instance type format
            if not instance_type_pattern.match(instance_type):
                invalid_specs.append(f"{instance_type} (invalid instance type)")
                continue
            
            # Create InstanceTypeSpec with default quantity of 1
            try:
                spec = InstanceTypeSpec(instance_type=instance_type, quantity=1)
                instance_type_specs.append(spec)
            except ValueError as e:
                invalid_specs.append(f"{spec_str} ({str(e)})")
    
    if invalid_specs:
        raise click.BadParameter(
            f"Invalid instance type specifications: {', '.join(invalid_specs)}. "
            f"Expected format: family.size or family.size:quantity (e.g., c7i.large, m7i.xlarge:2)"
        )
    
    # Calculate total instances to be launched
    total_instances = sum(spec.quantity for spec in instance_type_specs)
    
    # Warn if more than 3 instance types or more than 5 total instances
    if len(instance_type_specs) > 3 or total_instances > 5:
        click.echo(
            click.style(
                f"\nWarning: Testing {len(instance_type_specs)} instance type(s) "
                f"with {total_instances} total instance(s). "
                f"This may take significant time and incur costs.",
                fg='yellow'
            ),
            err=True
        )
        if not click.confirm("Do you want to continue?", default=False):
            ctx.exit(0)
    
    return instance_type_specs


def validate_subnet_id(ctx, param, value):
    """Validate subnet ID format.
    
    AWS subnet IDs follow the pattern: subnet-[0-9a-f]{8,17}
    Examples: subnet-12345678, subnet-1234567890abcdef0
    """
    if not value:
        raise click.BadParameter("Subnet ID is required")
    
    # AWS subnet ID pattern
    subnet_pattern = re.compile(r'^subnet-[0-9a-f]{8,17}$')
    
    if not subnet_pattern.match(value):
        raise click.BadParameter(
            f"Invalid subnet ID format: {value}. "
            f"Expected format: subnet-[0-9a-f]{{8,17}} (e.g., subnet-12345678)"
        )
    
    return value


def validate_private_key_path(ctx, param, value):
    """Validate private key file path and permissions.
    
    Checks:
    - File exists
    - File is readable
    - File permissions (warns if too permissive)
    """
    if not value:
        raise click.BadParameter("Private key path is required")
    
    key_path = Path(value)
    
    # Check if file exists
    if not key_path.exists():
        raise click.BadParameter(f"Private key file not found: {value}")
    
    # Check if it's a file (not a directory)
    if not key_path.is_file():
        raise click.BadParameter(f"Private key path is not a file: {value}")
    
    # Check if file is readable
    if not os.access(key_path, os.R_OK):
        raise click.BadParameter(f"Private key file is not readable: {value}")
    
    # Check file permissions (Unix-like systems only)
    if hasattr(os, 'stat'):
        try:
            file_stat = key_path.stat()
            file_mode = file_stat.st_mode & 0o777
            
            # Warn if permissions are too permissive (not 0600 or 0400)
            if file_mode not in (0o600, 0o400):
                click.echo(
                    click.style(
                        f"\nWarning: Private key file has permissive permissions ({oct(file_mode)}). "
                        f"Recommended: 0600 or 0400",
                        fg='yellow'
                    ),
                    err=True
                )
        except (OSError, AttributeError):
            # Skip permission check on systems that don't support it
            pass
    
    return str(key_path.absolute())


def validate_ami_id(ctx, param, value):
    """Validate AMI ID format if provided.
    
    AWS AMI IDs follow the pattern: ami-[0-9a-f]{8,17}
    Examples: ami-12345678, ami-1234567890abcdef0
    """
    if not value:
        return value
    
    # AWS AMI ID pattern
    ami_pattern = re.compile(r'^ami-[0-9a-f]{8,17}$')
    
    if not ami_pattern.match(value):
        raise click.BadParameter(
            f"Invalid AMI ID format: {value}. "
            f"Expected format: ami-[0-9a-f]{{8,17}} (e.g., ami-12345678)"
        )
    
    return value


def validate_security_group_id(ctx, param, value):
    """Validate security group ID format if provided.
    
    AWS security group IDs follow the pattern: sg-[0-9a-f]{8,17}
    Examples: sg-12345678, sg-1234567890abcdef0
    """
    if not value:
        return value
    
    # AWS security group ID pattern
    sg_pattern = re.compile(r'^sg-[0-9a-f]{8,17}$')
    
    if not sg_pattern.match(value):
        raise click.BadParameter(
            f"Invalid security group ID format: {value}. "
            f"Expected format: sg-[0-9a-f]{{8,17}} (e.g., sg-12345678)"
        )
    
    return value


def validate_region(ctx, param, value):
    """Validate AWS region format if provided.
    
    AWS regions follow patterns like: us-east-1, eu-west-2, ap-southeast-1
    """
    if not value:
        return value
    
    # AWS region pattern: region-direction-number
    region_pattern = re.compile(r'^[a-z]{2}-[a-z]+-[0-9]$')
    
    if not region_pattern.match(value):
        raise click.BadParameter(
            f"Invalid AWS region format: {value}. "
            f"Expected format: region-direction-number (e.g., us-east-1, eu-west-2)"
        )
    
    return value


@click.command()
@click.option(
    '--config',
    type=click.Path(exists=True),
    help='Path to configuration file (YAML or JSON format). Command-line arguments override config file values.'
)
@click.option(
    '--instance-types',
    callback=validate_instance_types,
    help='Comma-separated list of EC2 instance types to test with optional quantities. '
         'Format: type1,type2:qty2,type3:qty3 (e.g., c7i.large,m7i.xlarge:2,r6i.2xlarge:3)'
)
@click.option(
    '--subnet-id',
    callback=validate_subnet_id,
    help='AWS subnet ID where instances will be launched (e.g., subnet-12345678)'
)
@click.option(
    '--key-name',
    help='EC2 key pair name for SSH access'
)
@click.option(
    '--private-key-path',
    callback=validate_private_key_path,
    help='Path to private SSH key file (must be readable with secure permissions)'
)
@click.option(
    '--region',
    callback=validate_region,
    help='AWS region (optional, will be derived from subnet ID if not provided)'
)
@click.option(
    '--profile',
    help='AWS profile name (optional, uses default credentials if not provided)'
)
@click.option(
    '--ami-id',
    callback=validate_ami_id,
    help='AMI ID to use (optional, defaults to latest Amazon Linux 2023)'
)
@click.option(
    '--security-group-id',
    callback=validate_security_group_id,
    help='Security group ID for SSH access (optional, e.g., sg-12345678)'
)
@click.option(
    '--placement-group',
    help='Placement group name for instance placement (optional). The placement group must exist in the target region and be in available state.'
)
def main(config, instance_types, subnet_id, key_name, private_key_path, region, profile, ami_id, security_group_id, placement_group):
    """Test PTP hardware clock support on AWS EC2 instance types.
    
    This tool automates the process of discovering which EC2 instance types support
    AWS's nanosecond-precision hardware packet timestamping via PTP (Precision Time Protocol).
    
    The tool will:
    \b
    1. Launch EC2 instances with specified configurations
    2. Configure PTP hardware clocks automatically
    3. Verify PTP functionality
    4. Generate detailed reports
    5. Manage cleanup based on test results
    
    \b
    Configuration:
    
    Parameters can be provided via command-line arguments or a configuration file.
    Command-line arguments take precedence over config file values.
    
    Use --config to specify a YAML or JSON configuration file.
    See config.example.yaml or config.example.json for format examples.
    
    \b
    Examples:
    
    Test using a configuration file:
      ptp-tester --config my-config.yaml
    
    Test with config file and CLI overrides:
      ptp-tester --config my-config.yaml \\
                 --region us-west-2 \\
                 --instance-types c7i.large:3
    
    Test a single instance type (CLI only):
      ptp-tester --instance-types c7i.large \\
                 --subnet-id subnet-12345678 \\
                 --key-name my-key-pair \\
                 --private-key-path ~/.ssh/my-key.pem
    
    Test multiple instance types with custom region:
      ptp-tester --instance-types c7i.large,m7i.xlarge,r6i.2xlarge \\
                 --subnet-id subnet-12345678 \\
                 --key-name my-key-pair \\
                 --private-key-path ~/.ssh/my-key.pem \\
                 --region us-east-1
    
    Test with specific AWS profile and AMI:
      ptp-tester --instance-types c7i.large \\
                 --subnet-id subnet-12345678 \\
                 --key-name my-key-pair \\
                 --private-key-path ~/.ssh/my-key.pem \\
                 --profile production \\
                 --ami-id ami-1234567890abcdef0
    
    Test with placement group:
      ptp-tester --instance-types c7i.large:2 \\
                 --subnet-id subnet-12345678 \\
                 --key-name my-key-pair \\
                 --private-key-path ~/.ssh/my-key.pem \\
                 --placement-group my-cluster-pg
    
    \b
    Requirements:
    - AWS credentials configured (via profile, environment variables, or IAM role)
    - EC2 permissions: RunInstances, TerminateInstances, DescribeInstances, CreateTags
    - SSH access to the subnet
    - Private key file with secure permissions (0600 or 0400 recommended)
    - PyYAML library for YAML config files (pip install pyyaml)
    
    \b
    Notes:
    - Testing more than 3 instance types will prompt for confirmation
    - Instances without PTP support are automatically terminated
    - PTP-functional instances can be selectively kept or terminated
    - All operations are logged for audit purposes
    - Config files support both YAML (.yaml, .yml) and JSON (.json) formats
    """
    import logging
    from datetime import datetime
    from ptp_tester.aws_manager import AWSManager
    from ptp_tester.ssh_manager import SSHManager
    from ptp_tester.ptp_configurator import PTPConfigurator
    from ptp_tester.test_orchestrator import TestOrchestrator
    from ptp_tester.report_generator import ReportGenerator
    from ptp_tester.config_loader import ConfigLoader
    from ptp_tester.models import TestConfig
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(f'ptp_tester_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
        ]
    )
    logger = logging.getLogger(__name__)
    
    click.echo("PTP Instance Tester v0.1.0")
    click.echo("=" * 60)
    
    # Load configuration file if provided
    file_config = None
    if config:
        try:
            click.echo(f"\nLoading configuration from: {config}")
            config_loader = ConfigLoader()
            file_config = config_loader.load_config(config)
            click.echo(click.style("✓ Configuration file loaded successfully", fg='green'))
            logger.info(f"Configuration loaded from {config}")
        except (FileNotFoundError, ValueError) as e:
            click.echo(click.style(f"✗ Failed to load configuration file: {e}", fg='red'))
            logger.error(f"Failed to load configuration file: {e}")
            sys.exit(1)
    
    # Merge CLI arguments with config file (CLI takes precedence)
    # Start with config file values (if any), then override with CLI arguments
    if file_config:
        # Use config file values as defaults
        if instance_types is None and file_config.instance_types:
            instance_types = file_config.instance_types
            logger.info(f"Using instance_types from config file: {[str(s) for s in instance_types]}")
        
        if subnet_id is None and file_config.subnet_id:
            subnet_id = file_config.subnet_id
            logger.info(f"Using subnet_id from config file: {subnet_id}")
        
        if key_name is None and file_config.key_name:
            key_name = file_config.key_name
            logger.info(f"Using key_name from config file: {key_name}")
        
        if private_key_path is None and file_config.private_key_path:
            # Validate the private key path from config file
            try:
                private_key_path = validate_private_key_path(None, None, file_config.private_key_path)
                logger.info(f"Using private_key_path from config file: {private_key_path}")
            except click.BadParameter as e:
                click.echo(click.style(f"✗ Invalid private_key_path in config file: {e}", fg='red'))
                sys.exit(1)
        
        if region is None and file_config.region:
            region = file_config.region
            logger.info(f"Using region from config file: {region}")
        
        if profile is None and file_config.profile:
            profile = file_config.profile
            logger.info(f"Using profile from config file: {profile}")
        
        if ami_id is None and file_config.ami_id:
            ami_id = file_config.ami_id
            logger.info(f"Using ami_id from config file: {ami_id}")
        
        if security_group_id is None and file_config.security_group_id:
            security_group_id = file_config.security_group_id
            logger.info(f"Using security_group_id from config file: {security_group_id}")
        
        if placement_group is None and file_config.placement_group:
            placement_group = file_config.placement_group
            logger.info(f"Using placement_group from config file: {placement_group}")
    
    # Validate required parameters are present (after merging)
    missing_params = []
    if instance_types is None:
        missing_params.append("--instance-types")
    if subnet_id is None:
        missing_params.append("--subnet-id")
    if key_name is None:
        missing_params.append("--key-name")
    if private_key_path is None:
        missing_params.append("--private-key-path")
    
    if missing_params:
        click.echo(click.style(
            f"\n✗ Missing required parameters: {', '.join(missing_params)}\n"
            f"These must be provided either via command-line arguments or in a configuration file.",
            fg='red'
        ))
        logger.error(f"Missing required parameters: {missing_params}")
        sys.exit(1)
    
    # Display configuration
    click.echo("\nConfiguration:")
    # Display instance type specs with quantities
    spec_display = ', '.join(str(spec) for spec in instance_types)
    total_instances = sum(spec.quantity for spec in instance_types)
    click.echo(f"  Instance types: {spec_display} (total: {total_instances} instance(s))")
    click.echo(f"  Subnet ID: {subnet_id}")
    click.echo(f"  Key pair name: {key_name}")
    click.echo(f"  Private key: {private_key_path}")
    
    if region:
        click.echo(f"  Region: {region}")
    else:
        click.echo(f"  Region: (will be derived from subnet ID)")
    
    if profile:
        click.echo(f"  AWS Profile: {profile}")
    else:
        click.echo(f"  AWS Profile: (using default credentials)")
    
    if ami_id:
        click.echo(f"  AMI ID: {ami_id}")
    else:
        click.echo(f"  AMI ID: (will use latest Amazon Linux 2023)")
    
    if security_group_id:
        click.echo(f"  Security Group: {security_group_id}")
    else:
        click.echo(f"  Security Group: (will be determined automatically)")
    
    if placement_group:
        click.echo(f"  Placement Group: {placement_group}")
    else:
        click.echo(f"  Placement Group: (none - using default EC2 placement)")
    
    click.echo("\n" + "=" * 60)
    
    try:
        # Initialize components
        logger.info("Initializing components...")
        click.echo("\nInitializing AWS Manager...")
        
        aws_manager = AWSManager(region=region, profile=profile)
        logger.info(f"AWS Manager initialized (region: {aws_manager.region})")
        click.echo(f"  Region: {aws_manager.region}")
        
        click.echo("\nInitializing SSH Manager...")
        ssh_manager = SSHManager(private_key_path=private_key_path)
        logger.info("SSH Manager initialized")
        
        click.echo("Initializing PTP Configurator...")
        ptp_configurator = PTPConfigurator()
        logger.info("PTP Configurator initialized")
        
        click.echo("Initializing Test Orchestrator...")
        orchestrator = TestOrchestrator(
            aws_manager=aws_manager,
            ssh_manager=ssh_manager,
            ptp_configurator=ptp_configurator
        )
        logger.info("Test Orchestrator initialized")
        
        click.echo("Initializing Report Generator...")
        report_generator = ReportGenerator()
        logger.info("Report Generator initialized")
        
        click.echo("\n" + "=" * 60)
        click.echo("\nStarting PTP tests...")
        click.echo("=" * 60)
        
        # Validate placement group if provided
        if placement_group:
            click.echo(f"\nValidating placement group '{placement_group}'...")
            is_valid, error_msg = aws_manager.validate_placement_group(placement_group)
            
            if not is_valid:
                click.echo(click.style(f"✗ Placement group validation failed: {error_msg}", fg='red'))
                logger.error(f"Placement group validation failed: {error_msg}")
                sys.exit(1)
            
            click.echo(click.style(f"✓ Placement group '{placement_group}' is valid and available", fg='green'))
        
        # Prepare security group IDs list
        security_group_ids = [security_group_id] if security_group_id else None
        
        # Execute test workflow
        results = orchestrator.test_multiple_instances(
            instance_types=instance_types,
            subnet_id=subnet_id,
            key_name=key_name,
            ami_id=ami_id,
            security_group_ids=security_group_ids,
            placement_group=placement_group
        )
        
        if not results:
            click.echo(click.style("\nNo test results generated.", fg='red'))
            logger.error("No test results generated")
            sys.exit(1)
        
        # Generate and display reports
        click.echo("\n" + "=" * 60)
        click.echo("TEST RESULTS")
        click.echo("=" * 60)
        
        # Display individual instance reports
        for result in results:
            report = report_generator.generate_instance_report(result)
            click.echo(f"\n{report}")
        
        # Display summary report
        summary = report_generator.generate_summary_report(results)
        click.echo(f"\n{summary}")
        
        # Export results to JSON
        json_filename = f'ptp_test_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        report_generator.export_json(results, json_filename)
        click.echo(f"\nResults exported to: {json_filename}")
        logger.info(f"Results exported to {json_filename}")
        
        # Handle cleanup
        click.echo("\n" + "=" * 60)
        click.echo("CLEANUP")
        click.echo("=" * 60)
        
        # Separate supported and unsupported instances
        supported_results = [r for r in results if r.ptp_status.supported]
        unsupported_results = [r for r in results if not r.ptp_status.supported]
        
        # Auto-terminate unsupported instances
        if unsupported_results:
            click.echo(f"\nAuto-terminating {len(unsupported_results)} instance(s) without PTP support...")
            for result in unsupported_results:
                instance_id = result.instance_details.instance_id
                instance_type = result.instance_details.instance_type
                try:
                    click.echo(f"  Terminating {instance_type} ({instance_id})...")
                    aws_manager.terminate_instance(instance_id, verify=True)
                    click.echo(click.style(f"    ✓ Terminated", fg='green'))
                except Exception as e:
                    click.echo(click.style(f"    ✗ Failed: {e}", fg='red'))
                    logger.error(f"Failed to terminate {instance_id}: {e}")
        
        # Handle PTP-functional instances
        if supported_results:
            click.echo(f"\n{len(supported_results)} instance(s) with functional PTP:")
            for i, result in enumerate(supported_results, 1):
                details = result.instance_details
                click.echo(
                    f"\n  {i}. {details.instance_type} ({details.instance_id})\n"
                    f"     AZ: {details.availability_zone}\n"
                    f"     Subnet: {details.subnet_id}\n"
                    f"     Clock: {result.ptp_status.clock_device}"
                )
            
            # Prompt user for which instances to keep
            click.echo("\nSelect instances to keep (comma-separated numbers, 'all' to keep all, or 'none' to terminate all):")
            selection = click.prompt("Selection", default="all")
            
            if selection.lower() == 'all':
                click.echo("\nKeeping all PTP-functional instances.")
                logger.info("User chose to keep all PTP-functional instances")
            elif selection.lower() == 'none':
                click.echo("\nTerminating all PTP-functional instances...")
                logger.info("User chose to terminate all PTP-functional instances")
                
                for result in supported_results:
                    instance_id = result.instance_details.instance_id
                    instance_type = result.instance_details.instance_type
                    
                    click.echo(f"\nTerminating {instance_type} ({instance_id})...")
                    try:
                        aws_manager.terminate_instance(instance_id, verify=True)
                        click.echo(click.style(f"  ✓ Terminated", fg='green'))
                    except Exception as e:
                        click.echo(click.style(f"  ✗ Failed: {e}", fg='red'))
                        logger.error(f"Failed to terminate {instance_id}: {e}")
            else:
                try:
                    # Parse selection
                    selected_indices = [int(x.strip()) - 1 for x in selection.split(',')]
                    
                    # Terminate unselected instances
                    for i, result in enumerate(supported_results):
                        instance_id = result.instance_details.instance_id
                        instance_type = result.instance_details.instance_type
                        
                        if i not in selected_indices:
                            click.echo(f"\nTerminating {instance_type} ({instance_id})...")
                            try:
                                aws_manager.terminate_instance(instance_id, verify=True)
                                click.echo(click.style(f"  ✓ Terminated", fg='green'))
                            except Exception as e:
                                click.echo(click.style(f"  ✗ Failed: {e}", fg='red'))
                                logger.error(f"Failed to terminate {instance_id}: {e}")
                        else:
                            click.echo(f"\nKeeping {instance_type} ({instance_id})")
                            logger.info(f"Keeping instance {instance_id}")
                            
                except (ValueError, IndexError) as e:
                    click.echo(click.style(f"\nInvalid selection: {e}", fg='red'))
                    click.echo("Keeping all instances by default.")
                    logger.warning(f"Invalid selection, keeping all instances: {e}")
        
        click.echo("\n" + "=" * 60)
        click.echo(click.style("Testing complete!", fg='green'))
        click.echo("=" * 60)
        
    except KeyboardInterrupt:
        click.echo(click.style("\n\nOperation cancelled by user.", fg='yellow'))
        logger.warning("Operation cancelled by user")
        sys.exit(130)
        
    except Exception as e:
        click.echo(click.style(f"\n\nError: {e}", fg='red'))
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
