"""Data models for PTP Instance Tester."""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class InstanceTypeSpec:
    """Specification for an instance type with quantity."""
    instance_type: str
    quantity: int = 1
    
    def __post_init__(self):
        """Validate quantity is a positive integer."""
        if not isinstance(self.quantity, int):
            raise ValueError(f"Quantity must be an integer, got {type(self.quantity).__name__}")
        if self.quantity < 1:
            raise ValueError(f"Quantity must be positive, got {self.quantity}")
    
    def __str__(self) -> str:
        """Return formatted string representation."""
        if self.quantity == 1:
            return self.instance_type
        return f"{self.instance_type}:{self.quantity}"


@dataclass
class InstanceConfig:
    """Configuration for launching an EC2 instance."""
    instance_type: str
    subnet_id: str
    key_name: str
    ami_id: Optional[str] = None
    security_group_ids: Optional[List[str]] = None
    placement_group: Optional[str] = None


@dataclass
class InstanceDetails:
    """Details of an EC2 instance."""
    instance_id: str
    instance_type: str
    availability_zone: str
    subnet_id: str
    public_ip: Optional[str]
    private_ip: str
    state: str
    architecture: Optional[str] = None
    placement_group: Optional[str] = None


@dataclass
class CommandResult:
    """Result of an SSH command execution."""
    exit_code: int
    stdout: str
    stderr: str
    success: bool


@dataclass
class PTPStatus:
    """Status of PTP configuration and verification using AWS ENA chrony-based approach."""
    supported: bool
    ena_driver_version: Optional[str] = None
    ena_driver_compatible: bool = False
    hardware_clock_present: bool = False
    ptp_ena_symlink_present: bool = False
    chrony_using_phc: bool = False
    chrony_synchronized: bool = False
    clock_device: Optional[str] = None
    time_offset_ns: Optional[float] = None
    error_message: Optional[str] = None
    diagnostic_output: Optional[Dict[str, str]] = None


@dataclass
class TestResult:
    """Result of testing a single instance type."""
    instance_details: InstanceDetails
    ptp_status: PTPStatus
    configuration_success: bool
    timestamp: datetime
    duration_seconds: float


@dataclass
class TestConfig:
    """Configuration for PTP testing loaded from config file or CLI."""
    instance_types: Optional[List[InstanceTypeSpec]] = None
    subnet_id: Optional[str] = None
    key_name: Optional[str] = None
    private_key_path: Optional[str] = None
    region: Optional[str] = None
    profile: Optional[str] = None
    ami_id: Optional[str] = None
    security_group_id: Optional[str] = None
    placement_group: Optional[str] = None
    
    @classmethod
    def from_dict(cls, config_dict: Dict) -> 'TestConfig':
        """Create TestConfig from a dictionary (parsed from config file).
        
        Args:
            config_dict: Dictionary containing configuration parameters
            
        Returns:
            TestConfig object with values from dictionary
            
        Raises:
            ValueError: If instance_types format is invalid
        """
        from pathlib import Path
        
        # Parse instance_types if present
        instance_types = None
        if 'instance_types' in config_dict and config_dict['instance_types']:
            instance_types = []
            for spec in config_dict['instance_types']:
                if isinstance(spec, dict):
                    # Format: {"type": "c7i.large", "quantity": 2}
                    instance_type = spec.get('type')
                    quantity = spec.get('quantity', 1)
                    if not instance_type:
                        raise ValueError(f"Instance type specification missing 'type' field: {spec}")
                    instance_types.append(InstanceTypeSpec(instance_type=instance_type, quantity=quantity))
                elif isinstance(spec, str):
                    # Format: "c7i.large" or "c7i.large:2"
                    if ':' in spec:
                        parts = spec.split(':')
                        if len(parts) != 2:
                            raise ValueError(f"Invalid instance type specification: {spec}")
                        instance_type, quantity_str = parts
                        try:
                            quantity = int(quantity_str)
                        except ValueError:
                            raise ValueError(f"Invalid quantity in instance type specification: {spec}")
                        instance_types.append(InstanceTypeSpec(instance_type=instance_type, quantity=quantity))
                    else:
                        instance_types.append(InstanceTypeSpec(instance_type=spec, quantity=1))
                else:
                    raise ValueError(f"Invalid instance type specification format: {spec}")
        
        # Expand ~ in private_key_path if present
        private_key_path = config_dict.get('private_key_path')
        if private_key_path:
            private_key_path = str(Path(private_key_path).expanduser())
        
        return cls(
            instance_types=instance_types,
            subnet_id=config_dict.get('subnet_id'),
            key_name=config_dict.get('key_name'),
            private_key_path=private_key_path,
            region=config_dict.get('region'),
            profile=config_dict.get('profile'),
            ami_id=config_dict.get('ami_id'),
            security_group_id=config_dict.get('security_group_id'),
            placement_group=config_dict.get('placement_group')
        )
    
    def validate(self) -> List[str]:
        """Validate that required fields are present.
        
        Returns:
            List of error messages for missing required fields (empty if valid)
        """
        errors = []
        
        if not self.instance_types:
            errors.append("instance_types is required")
        
        if not self.subnet_id:
            errors.append("subnet_id is required")
        
        if not self.key_name:
            errors.append("key_name is required")
        
        if not self.private_key_path:
            errors.append("private_key_path is required")
        
        return errors
