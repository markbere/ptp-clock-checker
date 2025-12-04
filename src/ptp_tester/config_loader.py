"""Configuration file loader for PTP Instance Tester."""

import json
import logging
from pathlib import Path
from typing import Dict

from ptp_tester.models import TestConfig


logger = logging.getLogger(__name__)


class ConfigLoader:
    """Loads and parses configuration files in YAML or JSON format."""
    
    def __init__(self):
        """Initialize ConfigLoader."""
        self._yaml_available = False
        try:
            import yaml
            self._yaml_available = True
            self._yaml = yaml
        except ImportError:
            logger.warning("PyYAML not installed. YAML config files will not be supported.")
    
    def load_config(self, config_path: str) -> TestConfig:
        """Load configuration from a file.
        
        Supports both YAML (.yaml, .yml) and JSON (.json) formats.
        Format is auto-detected from file extension.
        
        Args:
            config_path: Path to configuration file
            
        Returns:
            TestConfig object with values from file
            
        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If file format is invalid or parsing fails
        """
        path = Path(config_path).expanduser()
        
        # Check if file exists
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        if not path.is_file():
            raise ValueError(f"Configuration path is not a file: {config_path}")
        
        # Determine format from extension
        extension = path.suffix.lower()
        
        try:
            with open(path, 'r') as f:
                if extension in ('.yaml', '.yml'):
                    config_dict = self._load_yaml(f, config_path)
                elif extension == '.json':
                    config_dict = self._load_json(f, config_path)
                else:
                    raise ValueError(
                        f"Unsupported config file format: {extension}. "
                        f"Supported formats: .yaml, .yml, .json"
                    )
        except (OSError, IOError) as e:
            raise ValueError(f"Failed to read configuration file: {e}")
        
        # Convert to TestConfig
        try:
            config = TestConfig.from_dict(config_dict)
            logger.info(f"Successfully loaded configuration from {config_path}")
            return config
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid configuration format: {e}")
    
    def _load_yaml(self, file_handle, config_path: str) -> Dict:
        """Load YAML configuration file.
        
        Args:
            file_handle: Open file handle
            config_path: Path to config file (for error messages)
            
        Returns:
            Dictionary with configuration values
            
        Raises:
            ValueError: If YAML parsing fails or PyYAML not installed
        """
        if not self._yaml_available:
            raise ValueError(
                "PyYAML library is not installed. "
                "Install it with: pip install pyyaml"
            )
        
        try:
            config_dict = self._yaml.safe_load(file_handle)
            
            if config_dict is None:
                raise ValueError("Configuration file is empty")
            
            if not isinstance(config_dict, dict):
                raise ValueError(
                    f"Configuration file must contain a YAML object/dictionary, "
                    f"got {type(config_dict).__name__}"
                )
            
            return config_dict
            
        except self._yaml.YAMLError as e:
            # Extract line number if available
            if hasattr(e, 'problem_mark'):
                mark = e.problem_mark
                raise ValueError(
                    f"YAML parsing error at line {mark.line + 1}, column {mark.column + 1}: {e}"
                )
            else:
                raise ValueError(f"YAML parsing error: {e}")
    
    def _load_json(self, file_handle, config_path: str) -> Dict:
        """Load JSON configuration file.
        
        Args:
            file_handle: Open file handle
            config_path: Path to config file (for error messages)
            
        Returns:
            Dictionary with configuration values
            
        Raises:
            ValueError: If JSON parsing fails
        """
        try:
            config_dict = json.load(file_handle)
            
            if not isinstance(config_dict, dict):
                raise ValueError(
                    f"Configuration file must contain a JSON object, "
                    f"got {type(config_dict).__name__}"
                )
            
            return config_dict
            
        except json.JSONDecodeError as e:
            raise ValueError(
                f"JSON parsing error at line {e.lineno}, column {e.colno}: {e.msg}"
            )
