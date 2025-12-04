"""SSH Manager for connecting to and executing commands on EC2 instances."""

import os
import stat
import time
import logging
from typing import Optional
import paramiko
from paramiko import SSHClient, AutoAddPolicy, RSAKey, Ed25519Key, ECDSAKey
from paramiko.ssh_exception import (
    SSHException,
    AuthenticationException,
    NoValidConnectionsError
)

from ptp_tester.models import CommandResult


logger = logging.getLogger(__name__)


class SSHManager:
    """Manages SSH connections and command execution on remote instances.
    
    This class handles:
    - SSH connection with private key authentication
    - Private key file permission validation
    - Connection retry logic with exponential backoff
    - Command execution with timeout handling
    - Secure key management (never logs or displays private key contents)
    """
    
    def __init__(self, private_key_path: str):
        """Initialize SSH Manager with private key.
        
        Args:
            private_key_path: Path to the SSH private key file
            
        Raises:
            FileNotFoundError: If private key file doesn't exist
            ValueError: If private key file has invalid permissions
        """
        self.private_key_path = private_key_path
        self._validate_key_file()
        self._private_key = None
        
    def _validate_key_file(self) -> None:
        """Validate private key file exists and has appropriate permissions.
        
        Warns if file permissions are overly permissive (not 0600 or 0400).
        
        Raises:
            FileNotFoundError: If private key file doesn't exist
        """
        if not os.path.exists(self.private_key_path):
            raise FileNotFoundError(
                f"Private key file not found: {self.private_key_path}"
            )
        
        # Check file permissions
        file_stat = os.stat(self.private_key_path)
        file_mode = stat.S_IMODE(file_stat.st_mode)
        
        # Acceptable permissions: 0600 (rw-------) or 0400 (r--------)
        acceptable_modes = [0o600, 0o400]
        
        if file_mode not in acceptable_modes:
            logger.warning(
                f"Private key file has overly permissive permissions: "
                f"{oct(file_mode)}. Recommended: 0600 or 0400. "
                f"Run: chmod 600 {self.private_key_path}"
            )
    
    def _load_private_key(self) -> paramiko.PKey:
        """Load private key from file.
        
        Tries multiple key types (RSA, Ed25519, ECDSA) to load the key.
        Never logs or displays the key contents.
        
        Returns:
            Loaded private key object
            
        Raises:
            SSHException: If key cannot be loaded
        """
        if self._private_key is not None:
            return self._private_key
        
        # Try different key types
        key_types = [RSAKey, Ed25519Key, ECDSAKey]
        
        for key_class in key_types:
            try:
                self._private_key = key_class.from_private_key_file(
                    self.private_key_path
                )
                logger.debug(f"Successfully loaded {key_class.__name__} private key")
                return self._private_key
            except Exception:
                continue
        
        raise SSHException(
            f"Failed to load private key from {self.private_key_path}. "
            "Ensure the file contains a valid SSH private key."
        )
    
    def _clear_private_key(self) -> None:
        """Clear private key from memory."""
        if self._private_key is not None:
            # Paramiko doesn't provide explicit key clearing, but we can
            # remove our reference to allow garbage collection
            self._private_key = None
    
    def connect(
        self,
        host: str,
        username: str = "ec2-user",
        port: int = 22,
        timeout: int = 30,
        max_retries: int = 3,
        initial_backoff: float = 5.0
    ) -> SSHClient:
        """Establish SSH connection to remote host with retry logic.
        
        Uses exponential backoff for retries. Connection attempts will be made
        with increasing delays: initial_backoff, initial_backoff*2, initial_backoff*4, etc.
        
        Args:
            host: Hostname or IP address to connect to
            username: SSH username (default: ec2-user for Amazon Linux)
            port: SSH port (default: 22)
            timeout: Connection timeout in seconds (default: 30)
            max_retries: Maximum number of connection attempts (default: 3)
            initial_backoff: Initial backoff delay in seconds (default: 5.0)
            
        Returns:
            Connected SSHClient instance
            
        Raises:
            SSHException: If connection fails after all retries
            AuthenticationException: If authentication fails
        """
        private_key = self._load_private_key()
        
        client = SSHClient()
        client.set_missing_host_key_policy(AutoAddPolicy())
        
        last_exception = None
        backoff = initial_backoff
        
        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Attempting SSH connection to {username}@{host}:{port} "
                    f"(attempt {attempt + 1}/{max_retries})"
                )
                
                client.connect(
                    hostname=host,
                    port=port,
                    username=username,
                    pkey=private_key,
                    timeout=timeout,
                    look_for_keys=False,
                    allow_agent=False
                )
                
                logger.info(f"Successfully connected to {host}")
                return client
                
            except (SSHException, NoValidConnectionsError, TimeoutError) as e:
                last_exception = e
                
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Connection attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {backoff} seconds..."
                    )
                    time.sleep(backoff)
                    backoff *= 2  # Exponential backoff
                else:
                    logger.error(
                        f"All {max_retries} connection attempts failed"
                    )
            
            except AuthenticationException as e:
                # Authentication errors are not retryable
                logger.error(f"Authentication failed: {e}")
                client.close()
                raise
        
        # All retries exhausted
        client.close()
        raise SSHException(
            f"Failed to connect to {host} after {max_retries} attempts. "
            f"Last error: {last_exception}"
        )
    
    def execute_command(
        self,
        client: SSHClient,
        command: str,
        timeout: int = 120
    ) -> CommandResult:
        """Execute a command on the remote host via SSH.
        
        Args:
            client: Connected SSHClient instance
            command: Command to execute
            timeout: Command execution timeout in seconds (default: 120)
            
        Returns:
            CommandResult with exit code, stdout, stderr, and success status
            
        Raises:
            SSHException: If command execution fails
            TimeoutError: If command execution exceeds timeout
        """
        try:
            logger.debug(f"Executing command: {command[:100]}...")  # Log first 100 chars
            
            stdin, stdout, stderr = client.exec_command(
                command,
                timeout=timeout
            )
            
            # Wait for command to complete and read output
            exit_code = stdout.channel.recv_exit_status()
            stdout_text = stdout.read().decode('utf-8', errors='replace')
            stderr_text = stderr.read().decode('utf-8', errors='replace')
            
            success = (exit_code == 0)
            
            if success:
                logger.debug(f"Command completed successfully (exit code: {exit_code})")
            else:
                logger.warning(
                    f"Command failed with exit code {exit_code}. "
                    f"stderr: {stderr_text[:200]}"  # Log first 200 chars of error
                )
            
            return CommandResult(
                exit_code=exit_code,
                stdout=stdout_text,
                stderr=stderr_text,
                success=success
            )
            
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            raise SSHException(f"Failed to execute command: {e}")
    
    def disconnect(self, client: SSHClient) -> None:
        """Close SSH connection and clear private key from memory.
        
        Args:
            client: SSHClient instance to disconnect
        """
        try:
            if client:
                client.close()
                logger.debug("SSH connection closed")
        finally:
            # Always clear private key from memory
            self._clear_private_key()
    
    def __del__(self):
        """Ensure private key is cleared when object is destroyed."""
        self._clear_private_key()
