"""AWS Manager component for EC2 instance operations."""

import logging
import re
import time
from typing import Optional, Tuple

import boto3
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    NoCredentialsError,
    PartialCredentialsError,
)

from .models import InstanceConfig, InstanceDetails

# Configure logging
logger = logging.getLogger(__name__)


class AWSManager:
    """Manages AWS EC2 operations for PTP testing.
    
    This class handles:
    - AWS credential resolution and validation
    - EC2 instance lifecycle management (launch, monitor, terminate)
    - Region extraction from subnet IDs
    - Security and audit logging
    """

    def __init__(self, region: Optional[str] = None, profile: Optional[str] = None):
        """Initialize AWS Manager with credentials and region.
        
        Args:
            region: AWS region (optional, can be derived from subnet ID)
            profile: AWS profile name (optional, uses default credential chain if not provided)
            
        Raises:
            NoCredentialsError: If AWS credentials cannot be found
            PartialCredentialsError: If AWS credentials are incomplete
            ClientError: If credential validation fails
        """
        self.profile = profile
        self.region = region
        self._session = None
        self._ec2_client = None
        self._ssm_client = None
        
        # Initialize session and validate credentials
        self._initialize_session()
        self._validate_credentials()
        
    def _initialize_session(self):
        """Initialize boto3 session with proper credential resolution.
        
        Follows AWS SDK best practices:
        1. Use provided profile if specified
        2. Fall back to default credential chain (env vars, credentials file, IAM role)
        
        Never hardcodes credentials - relies on AWS SDK credential resolution.
        """
        try:
            if self.profile:
                logger.info(f"Initializing AWS session with profile: {self.profile}")
                self._session = boto3.Session(profile_name=self.profile)
            else:
                logger.info("Initializing AWS session with default credential chain")
                self._session = boto3.Session()
                
            # Log credential source without exposing secrets
            credentials = self._session.get_credentials()
            if credentials:
                # Determine credential source
                if hasattr(credentials, 'method'):
                    logger.info(f"Credential source: {credentials.method}")
                
                # Log profile name if available
                if self.profile:
                    logger.info(f"Using AWS profile: {self.profile}")
                    
                # Try to get role ARN if using assumed role (without exposing secrets)
                try:
                    sts_client = self._session.client('sts')
                    caller_identity = sts_client.get_caller_identity()
                    arn = caller_identity.get('Arn', 'Unknown')
                    logger.info(f"AWS identity ARN: {arn}")
                except Exception as e:
                    logger.debug(f"Could not retrieve caller identity: {e}")
            else:
                logger.warning("No credentials found in session")
                
        except Exception as e:
            logger.error(f"Failed to initialize AWS session: {e}")
            raise
            
    def _validate_credentials(self):
        """Validate AWS credentials before attempting operations.
        
        Makes a simple STS call to verify credentials are valid and not expired.
        
        Raises:
            NoCredentialsError: If no credentials are configured
            PartialCredentialsError: If credentials are incomplete
            ClientError: If credentials are invalid or expired
        """
        try:
            sts_client = self._session.client('sts')
            response = sts_client.get_caller_identity()
            
            account_id = response.get('Account', 'Unknown')
            user_id = response.get('UserId', 'Unknown')
            
            logger.info(f"Credentials validated successfully")
            logger.info(f"AWS Account ID: {account_id}")
            logger.debug(f"User ID: {user_id}")
            
        except NoCredentialsError:
            logger.error("No AWS credentials found. Please configure credentials.")
            raise
        except PartialCredentialsError:
            logger.error("Incomplete AWS credentials. Please check your configuration.")
            raise
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code in ['InvalidClientTokenId', 'SignatureDoesNotMatch', 'ExpiredToken']:
                logger.error(f"Invalid or expired AWS credentials: {error_code}")
            else:
                logger.error(f"Failed to validate credentials: {e}")
            raise
        except BotoCoreError as e:
            logger.error(f"AWS SDK error during credential validation: {e}")
            raise
            
    def _get_region_from_subnet(self, subnet_id: str) -> str:
        """Extract region from subnet ID by querying AWS.
        
        Args:
            subnet_id: AWS subnet ID (e.g., subnet-12345678)
            
        Returns:
            AWS region string (e.g., us-east-1)
            
        Raises:
            ClientError: If subnet cannot be found or accessed
        """
        # Try each region until we find the subnet
        # This is necessary because subnet IDs don't encode region information
        ec2_client = self._session.client('ec2')
        
        try:
            # First, try to describe the subnet without specifying region
            # This will use the default region from the session
            response = ec2_client.describe_subnets(SubnetIds=[subnet_id])
            subnets = response.get('Subnets', [])
            
            if subnets:
                # Get the availability zone and extract region
                az = subnets[0].get('AvailabilityZone', '')
                # Region is AZ without the last character (e.g., us-east-1a -> us-east-1)
                region = az[:-1] if az else None
                
                if region:
                    logger.info(f"Extracted region '{region}' from subnet {subnet_id}")
                    return region
                    
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            
            # If subnet not found in default region, we need to search other regions
            if error_code == 'InvalidSubnetID.NotFound':
                logger.warning(f"Subnet {subnet_id} not found in default region, searching other regions...")
                
                # Get list of all regions
                ec2_client = self._session.client('ec2')
                regions_response = ec2_client.describe_regions()
                regions = [r['RegionName'] for r in regions_response.get('Regions', [])]
                
                # Try each region
                for region in regions:
                    try:
                        regional_client = self._session.client('ec2', region_name=region)
                        response = regional_client.describe_subnets(SubnetIds=[subnet_id])
                        subnets = response.get('Subnets', [])
                        
                        if subnets:
                            logger.info(f"Found subnet {subnet_id} in region {region}")
                            return region
                    except ClientError:
                        continue
                        
                # If we get here, subnet wasn't found in any region
                logger.error(f"Subnet {subnet_id} not found in any region")
                raise ValueError(f"Subnet {subnet_id} not found in any accessible region")
            else:
                logger.error(f"Error querying subnet {subnet_id}: {e}")
                raise
                
        # Fallback: couldn't determine region
        raise ValueError(f"Could not determine region from subnet {subnet_id}")
        
    def _ensure_region(self, subnet_id: Optional[str] = None) -> str:
        """Ensure region is set, deriving from subnet if necessary.
        
        Args:
            subnet_id: Optional subnet ID to derive region from
            
        Returns:
            AWS region string
            
        Raises:
            ValueError: If region cannot be determined
        """
        if self.region:
            return self.region
            
        if subnet_id:
            self.region = self._get_region_from_subnet(subnet_id)
            return self.region
            
        # Try to get default region from session
        if self._session.region_name:
            self.region = self._session.region_name
            logger.info(f"Using default region from session: {self.region}")
            return self.region
            
        raise ValueError("Region must be specified or derivable from subnet ID")
        
    def _get_ec2_client(self):
        """Get or create EC2 client for the configured region.
        
        Returns:
            boto3 EC2 client
        """
        if not self._ec2_client or (self.region and self._ec2_client.meta.region_name != self.region):
            if not self.region:
                raise ValueError("Region must be set before creating EC2 client")
            self._ec2_client = self._session.client('ec2', region_name=self.region)
            logger.debug(f"Created EC2 client for region: {self.region}")
        return self._ec2_client
        
    def _get_ssm_client(self):
        """Get or create SSM client for the configured region.
        
        Returns:
            boto3 SSM client
        """
        if not self._ssm_client or (self.region and self._ssm_client.meta.region_name != self.region):
            if not self.region:
                raise ValueError("Region must be set before creating SSM client")
            self._ssm_client = self._session.client('ssm', region_name=self.region)
            logger.debug(f"Created SSM client for region: {self.region}")
        return self._ssm_client

    def _get_instance_type_architecture(self, instance_type: str) -> str:
        """Determine the CPU architecture for a given instance type.
        
        Maps instance families to their architectures:
        - Graviton (ARM64): c6gn, c7gn, c6g, c7g, m6g, m7g, r6g, r7g, t4g
        - x86_64: c6i, c7i, c6a, c7a, m6i, m7i, r6i, r7i, c5n
        
        Args:
            instance_type: EC2 instance type (e.g., 'c7gn.xlarge', 'c7i.large')
            
        Returns:
            Architecture string: 'arm64' for Graviton, 'x86_64' for Intel/AMD
            Defaults to 'x86_64' for unknown instance types
        """
        # Extract instance family from instance type (e.g., 'c7gn' from 'c7gn.xlarge')
        # Instance type format: <family>.<size>
        family = instance_type.split('.')[0] if '.' in instance_type else instance_type
        
        # Graviton (ARM64) instance families
        graviton_families = {
            'c6gn', 'c7gn',  # Compute optimized with network
            'c6g', 'c7g',    # Compute optimized
            'm6g', 'm7g',    # General purpose
            'r6g', 'r7g',    # Memory optimized
            't4g'            # Burstable
        }
        
        # x86_64 instance families (explicitly mapped for clarity)
        x86_64_families = {
            'c6i', 'c7i',    # Compute optimized Intel
            'c6a', 'c7a',    # Compute optimized AMD
            'm6i', 'm7i',    # General purpose Intel
            'r6i', 'r7i',    # Memory optimized Intel
            'c5n'            # Compute optimized with network (older gen)
        }
        
        # Determine architecture
        if family in graviton_families:
            architecture = 'arm64'
            logger.info(f"Instance type {instance_type} (family: {family}) mapped to architecture: {architecture}")
        elif family in x86_64_families:
            architecture = 'x86_64'
            logger.info(f"Instance type {instance_type} (family: {family}) mapped to architecture: {architecture}")
        else:
            # Default to x86_64 for unknown instance types
            architecture = 'x86_64'
            logger.warning(
                f"Instance type {instance_type} (family: {family}) not in known mappings, "
                f"defaulting to architecture: {architecture}"
            )
        
        return architecture

    def get_latest_al2023_ami(self, architecture: str = 'x86_64') -> str:
        """Query SSM Parameter Store for latest Amazon Linux 2023 AMI.
        
        Args:
            architecture: CPU architecture ('x86_64' or 'arm64'), defaults to 'x86_64'
            
        Returns:
            AMI ID string
            
        Raises:
            ClientError: If AMI cannot be retrieved
            ValueError: If architecture is not supported
        """
        ssm_client = self._get_ssm_client()
        
        # Validate architecture
        if architecture not in ['x86_64', 'arm64']:
            raise ValueError(f"Unsupported architecture: {architecture}. Must be 'x86_64' or 'arm64'")
        
        try:
            # Map architecture to SSM parameter name
            parameter_name = f'/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-{architecture}'
            
            logger.info(f"Querying SSM for latest Amazon Linux 2023 AMI (architecture: {architecture})")
            logger.debug(f"SSM parameter: {parameter_name}")
            
            response = ssm_client.get_parameter(Name=parameter_name)
            
            ami_id = response['Parameter']['Value']
            logger.info(f"Latest Amazon Linux 2023 AMI for {architecture}: {ami_id}")
            
            return ami_id
            
        except ClientError as e:
            logger.error(f"Failed to retrieve latest AL2023 AMI for {architecture} from SSM: {e}")
            raise
            
    def launch_instance(self, config: InstanceConfig) -> InstanceDetails:
        """Launch an EC2 instance with the specified configuration.
        
        Args:
            config: Instance configuration
            
        Returns:
            InstanceDetails with information about the launched instance
            
        Raises:
            ClientError: If instance launch fails
            ValueError: If configuration is invalid
        """
        # Ensure region is set
        self._ensure_region(config.subnet_id)
        ec2_client = self._get_ec2_client()
        
        # Detect architecture from instance type
        architecture = self._get_instance_type_architecture(config.instance_type)
        logger.info(f"Detected architecture for instance type {config.instance_type}: {architecture}")
        
        # Determine AMI ID
        ami_id = config.ami_id
        if not ami_id:
            logger.info(f"No AMI ID provided, querying for latest Amazon Linux 2023 ({architecture})")
            ami_id = self.get_latest_al2023_ami(architecture=architecture)
        else:
            logger.info(f"Using provided AMI ID: {ami_id} for architecture: {architecture}")
            
        # Validate security groups if provided
        security_group_ids = config.security_group_ids or []
        if security_group_ids:
            logger.info(f"Using provided security groups: {security_group_ids}")
        else:
            logger.warning("No security groups provided - instance may not be accessible via SSH")
            
        # Prepare launch parameters
        launch_params = {
            'ImageId': ami_id,
            'InstanceType': config.instance_type,
            'KeyName': config.key_name,
            'SubnetId': config.subnet_id,
            'MinCount': 1,
            'MaxCount': 1,
            'MetadataOptions': {
                # Enable IMDSv2 for enhanced security
                'HttpTokens': 'required',
                'HttpPutResponseHopLimit': 1,
                'HttpEndpoint': 'enabled'
            },
            'TagSpecifications': [
                {
                    'ResourceType': 'instance',
                    'Tags': [
                        {'Key': 'Name', 'Value': f'ptp-tester-{config.instance_type}'},
                        {'Key': 'Purpose', 'Value': 'PTP Hardware Clock Testing'},
                        {'Key': 'ManagedBy', 'Value': 'ptp-instance-tester'},
                        {'Key': 'InstanceType', 'Value': config.instance_type}
                    ]
                }
            ]
        }
        
        # Add security groups if provided
        if security_group_ids:
            launch_params['SecurityGroupIds'] = security_group_ids
        
        # Add placement group if provided
        if config.placement_group:
            launch_params['Placement'] = {'GroupName': config.placement_group}
            logger.info(f"Instance will be launched into placement group: {config.placement_group}")
            
        try:
            logger.info(f"Launching instance: type={config.instance_type}, subnet={config.subnet_id}, ami={ami_id}")
            logger.info(f"Launch parameters: {launch_params}")
            
            response = ec2_client.run_instances(**launch_params)
            
            instance = response['Instances'][0]
            instance_id = instance['InstanceId']
            
            logger.info(f"Instance launched successfully: {instance_id}")
            
            # Extract placement group if present
            placement_group = instance.get('Placement', {}).get('GroupName')
            
            # Extract instance details
            instance_details = InstanceDetails(
                instance_id=instance_id,
                instance_type=instance['InstanceType'],
                availability_zone=instance['Placement']['AvailabilityZone'],
                subnet_id=instance['SubnetId'],
                public_ip=instance.get('PublicIpAddress'),
                private_ip=instance.get('PrivateIpAddress', ''),
                state=instance['State']['Name'],
                architecture=architecture,
                placement_group=placement_group
            )
            
            logger.info(f"Instance details: ID={instance_id}, Type={instance['InstanceType']}, "
                       f"AZ={instance['Placement']['AvailabilityZone']}, Architecture={architecture}")
            
            return instance_details
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            
            logger.error(f"Failed to launch instance: {error_code} - {error_message}")
            
            # Provide helpful error messages for common issues
            if error_code == 'InvalidSubnetID.NotFound':
                raise ValueError(f"Subnet {config.subnet_id} not found in region {self.region}")
            elif error_code == 'InvalidKeyPair.NotFound':
                raise ValueError(f"Key pair '{config.key_name}' not found in region {self.region}")
            elif error_code == 'InvalidAMIID.NotFound':
                raise ValueError(f"AMI {ami_id} not found in region {self.region}")
            elif error_code == 'InvalidGroup.NotFound':
                raise ValueError(f"One or more security groups not found: {security_group_ids}")
            elif error_code == 'Unsupported':
                raise ValueError(f"Instance type {config.instance_type} not supported in this region/AZ")
            elif error_code == 'InsufficientInstanceCapacity':
                raise RuntimeError(f"Insufficient capacity for instance type {config.instance_type}")
            else:
                raise RuntimeError(f"Failed to launch instance: {error_message}")
                
    def wait_for_running(self, instance_id: str, timeout: int = 300) -> InstanceDetails:
        """Wait for an instance to reach 'running' state.
        
        Args:
            instance_id: EC2 instance ID
            timeout: Maximum time to wait in seconds (default: 300 = 5 minutes)
            
        Returns:
            InstanceDetails with updated information
            
        Raises:
            TimeoutError: If instance doesn't reach running state within timeout
            ClientError: If instance query fails
        """
        ec2_client = self._get_ec2_client()
        
        logger.info(f"Waiting for instance {instance_id} to reach 'running' state (timeout: {timeout}s)")
        
        start_time = time.time()
        
        while True:
            elapsed = time.time() - start_time
            
            if elapsed > timeout:
                raise TimeoutError(
                    f"Instance {instance_id} did not reach 'running' state within {timeout} seconds"
                )
                
            try:
                response = ec2_client.describe_instances(InstanceIds=[instance_id])
                
                if not response['Reservations']:
                    raise ValueError(f"Instance {instance_id} not found")
                    
                instance = response['Reservations'][0]['Instances'][0]
                state = instance['State']['Name']
                
                logger.debug(f"Instance {instance_id} state: {state} (elapsed: {elapsed:.1f}s)")
                
                if state == 'running':
                    logger.info(f"Instance {instance_id} is now running (took {elapsed:.1f}s)")
                    
                    # Detect architecture from instance type
                    instance_type = instance['InstanceType']
                    architecture = self._get_instance_type_architecture(instance_type)
                    
                    # Extract placement group if present
                    placement_group = instance.get('Placement', {}).get('GroupName')
                    
                    # Return updated instance details
                    instance_details = InstanceDetails(
                        instance_id=instance['InstanceId'],
                        instance_type=instance_type,
                        availability_zone=instance['Placement']['AvailabilityZone'],
                        subnet_id=instance['SubnetId'],
                        public_ip=instance.get('PublicIpAddress'),
                        private_ip=instance.get('PrivateIpAddress', ''),
                        state=state,
                        architecture=architecture,
                        placement_group=placement_group
                    )
                    
                    logger.info(f"Instance details: ID={instance_id}, Type={instance_type}, "
                               f"State={state}, Architecture={architecture}")
                    
                    return instance_details
                elif state in ['terminated', 'terminating']:
                    raise RuntimeError(f"Instance {instance_id} is {state}")
                elif state in ['stopped', 'stopping']:
                    raise RuntimeError(f"Instance {instance_id} is {state}")
                    
                # Wait before checking again
                time.sleep(5)
                
            except ClientError as e:
                logger.error(f"Error checking instance state: {e}")
                raise
                
    def get_instance_details(self, instance_id: str) -> InstanceDetails:
        """Get current details of an EC2 instance.
        
        Args:
            instance_id: EC2 instance ID
            
        Returns:
            InstanceDetails with current information
            
        Raises:
            ClientError: If instance query fails
            ValueError: If instance not found
        """
        ec2_client = self._get_ec2_client()
        
        try:
            response = ec2_client.describe_instances(InstanceIds=[instance_id])
            
            if not response['Reservations']:
                raise ValueError(f"Instance {instance_id} not found")
                
            instance = response['Reservations'][0]['Instances'][0]
            
            # Detect architecture from instance type
            instance_type = instance['InstanceType']
            architecture = self._get_instance_type_architecture(instance_type)
            
            # Extract placement group if present
            placement_group = instance.get('Placement', {}).get('GroupName')
            
            instance_details = InstanceDetails(
                instance_id=instance['InstanceId'],
                instance_type=instance_type,
                availability_zone=instance['Placement']['AvailabilityZone'],
                subnet_id=instance['SubnetId'],
                public_ip=instance.get('PublicIpAddress'),
                private_ip=instance.get('PrivateIpAddress', ''),
                state=instance['State']['Name'],
                architecture=architecture,
                placement_group=placement_group
            )
            
            logger.debug(f"Retrieved instance details: ID={instance['InstanceId']}, "
                        f"Type={instance_type}, Architecture={architecture}")
            
            return instance_details
            
        except ClientError as e:
            logger.error(f"Failed to get instance details: {e}")
            raise
            
    def validate_placement_group(self, placement_group_name: str) -> tuple[bool, Optional[str]]:
        """Validate that a placement group exists and is available.
        
        Args:
            placement_group_name: Name of the placement group to validate
            
        Returns:
            Tuple of (is_valid: bool, error_message: Optional[str])
            - (True, None) if placement group exists and is available
            - (False, error_message) if placement group is invalid or unavailable
        """
        ec2_client = self._get_ec2_client()
        
        try:
            logger.info(f"Validating placement group: {placement_group_name}")
            
            response = ec2_client.describe_placement_groups(
                GroupNames=[placement_group_name]
            )
            
            placement_groups = response.get('PlacementGroups', [])
            
            if not placement_groups:
                error_msg = f"Placement group '{placement_group_name}' not found in region {self.region}"
                logger.error(error_msg)
                return (False, error_msg)
            
            pg = placement_groups[0]
            state = pg.get('State', 'unknown')
            strategy = pg.get('Strategy', 'unknown')
            
            logger.info(
                f"Placement group '{placement_group_name}' found: "
                f"strategy={strategy}, state={state}"
            )
            
            # Check if placement group is available
            if state != 'available':
                error_msg = (
                    f"Placement group '{placement_group_name}' is not available "
                    f"(current state: {state})"
                )
                logger.error(error_msg)
                return (False, error_msg)
            
            # Log placement group details
            logger.info(f"Placement group validation successful:")
            logger.info(f"  Name: {placement_group_name}")
            logger.info(f"  Strategy: {strategy}")
            logger.info(f"  State: {state}")
            
            if strategy == 'partition':
                partition_count = pg.get('PartitionCount', 'N/A')
                logger.info(f"  Partition Count: {partition_count}")
            
            return (True, None)
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            
            if error_code == 'InvalidPlacementGroup.Unknown':
                error_msg = f"Placement group '{placement_group_name}' not found in region {self.region}"
                logger.error(error_msg)
                return (False, error_msg)
            else:
                error_msg = f"Error validating placement group: {error_code} - {error_message}"
                logger.error(error_msg)
                return (False, error_msg)
    
    def terminate_instance(self, instance_id: str, verify: bool = True) -> bool:
        """Terminate an EC2 instance.
        
        Args:
            instance_id: EC2 instance ID
            verify: Whether to verify termination completed (default: True)
            
        Returns:
            True if termination successful, False otherwise
            
        Raises:
            ClientError: If termination request fails
        """
        ec2_client = self._get_ec2_client()
        
        try:
            logger.info(f"Terminating instance {instance_id}")
            
            response = ec2_client.terminate_instances(InstanceIds=[instance_id])
            
            current_state = response['TerminatingInstances'][0]['CurrentState']['Name']
            logger.info(f"Instance {instance_id} termination initiated, current state: {current_state}")
            
            if verify:
                # Wait for termination to complete (up to 2 minutes)
                logger.info(f"Verifying termination of instance {instance_id}")
                timeout = 120
                start_time = time.time()
                
                while True:
                    elapsed = time.time() - start_time
                    
                    if elapsed > timeout:
                        logger.warning(
                            f"Termination verification timed out after {timeout}s. "
                            f"Instance {instance_id} may still be terminating."
                        )
                        return False
                        
                    try:
                        details = self.get_instance_details(instance_id)
                        state = details.state
                        
                        logger.debug(f"Instance {instance_id} state: {state}")
                        
                        if state == 'terminated':
                            logger.info(f"Instance {instance_id} successfully terminated (took {elapsed:.1f}s)")
                            return True
                        elif state != 'terminating':
                            logger.warning(f"Instance {instance_id} in unexpected state: {state}")
                            return False
                            
                        time.sleep(5)
                        
                    except ValueError:
                        # Instance not found - consider it terminated
                        logger.info(f"Instance {instance_id} no longer found - termination complete")
                        return True
                    except ClientError as e:
                        error_code = e.response.get('Error', {}).get('Code', '')
                        if error_code == 'InvalidInstanceID.NotFound':
                            logger.info(f"Instance {instance_id} no longer found - termination complete")
                            return True
                        raise
            else:
                # Don't verify, just return True after initiating termination
                return True
                
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            
            logger.error(f"Failed to terminate instance {instance_id}: {error_code} - {error_message}")
            
            if error_code == 'InvalidInstanceID.NotFound':
                logger.warning(f"Instance {instance_id} not found - may already be terminated")
                return True
            else:
                raise
