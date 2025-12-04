"""Report generation for PTP Instance Tester."""

import json
from datetime import datetime
from typing import List, Dict, Any
from .models import TestResult, PTPStatus, InstanceDetails


class ReportGenerator:
    """Generates reports from PTP test results."""
    
    def __init__(self):
        """Initialize the report generator."""
        pass
    
    def generate_instance_report(self, result: TestResult) -> str:
        """
        Generate a human-readable report for a single instance test.
        
        Args:
            result: TestResult containing instance and PTP status information
            
        Returns:
            Formatted string report with all required fields
        """
        lines = []
        lines.append("=" * 70)
        lines.append(f"Instance Type: {result.instance_details.instance_type}")
        lines.append(f"Instance ID: {result.instance_details.instance_id}")
        
        # Include architecture if available
        if result.instance_details.architecture:
            lines.append(f"Architecture: {result.instance_details.architecture}")
        
        lines.append(f"Availability Zone: {result.instance_details.availability_zone}")
        lines.append(f"Subnet ID: {result.instance_details.subnet_id}")
        
        # Include placement group if present
        if result.instance_details.placement_group:
            lines.append(f"Placement Group: {result.instance_details.placement_group}")
        
        # Sanitize IP addresses - show only first two octets
        if result.instance_details.public_ip:
            sanitized_public = self._sanitize_ip(result.instance_details.public_ip)
            lines.append(f"Public IP: {sanitized_public}")
        
        sanitized_private = self._sanitize_ip(result.instance_details.private_ip)
        lines.append(f"Private IP: {sanitized_private}")
        
        lines.append(f"State: {result.instance_details.state}")
        lines.append(f"Test Timestamp: {result.timestamp.isoformat()}")
        lines.append(f"Test Duration: {result.duration_seconds:.2f} seconds")
        lines.append("-" * 70)
        
        # Test status
        lines.append(f"Configuration Success: {result.configuration_success}")
        lines.append(f"PTP Supported: {result.ptp_status.supported}")
        
        # Verification details
        lines.append("\nVerification Details:")
        lines.append(f"  ENA Driver Version: {result.ptp_status.ena_driver_version or 'Unknown'}")
        lines.append(f"  ENA Driver Compatible: {result.ptp_status.ena_driver_compatible}")
        lines.append(f"  Hardware Clock Present: {result.ptp_status.hardware_clock_present}")
        lines.append(f"  /dev/ptp_ena Symlink Present: {result.ptp_status.ptp_ena_symlink_present}")
        lines.append(f"  Chrony Using PHC: {result.ptp_status.chrony_using_phc}")
        lines.append(f"  Chrony Synchronized: {result.ptp_status.chrony_synchronized}")
        
        # Conditional fields based on PTP functionality
        if result.ptp_status.supported:
            # Include clock information for functional PTP
            lines.append("\nPTP Clock Information:")
            lines.append(f"  Clock Device: {result.ptp_status.clock_device or 'N/A'}")
            if result.ptp_status.time_offset_ns is not None:
                lines.append(f"  Time Offset: {result.ptp_status.time_offset_ns:.2f} ns")
        else:
            # Include diagnostic information for non-functional PTP
            lines.append("\nDiagnostic Information:")
            if result.ptp_status.error_message:
                lines.append(f"  Error: {result.ptp_status.error_message}")
            
            if result.ptp_status.diagnostic_output:
                # Check for troubleshooting results first
                if 'troubleshooting' in result.ptp_status.diagnostic_output:
                    troubleshooting = result.ptp_status.diagnostic_output['troubleshooting']
                    lines.append("  Troubleshooting Results:")
                    
                    summary = troubleshooting.get('summary', {})
                    lines.append(
                        f"    Checks: {summary.get('passed', 0)}/{summary.get('total_checks', 0)} passed, "
                        f"{summary.get('failed', 0)} failed, {summary.get('warnings', 0)} warnings"
                    )
                    
                    issues = troubleshooting.get('issues_found', [])
                    if issues:
                        lines.append(f"    Issues Found ({len(issues)}):")
                        for issue in issues[:5]:  # Show first 5 issues
                            lines.append(f"      - {issue}")
                    
                    recommendations = troubleshooting.get('recommendations', [])
                    if recommendations:
                        lines.append(f"    Recommendations ({len(recommendations)}):")
                        for rec in recommendations[:5]:  # Show first 5 recommendations
                            lines.append(f"      - {rec}")
                    
                    lines.append("")
                
                # Show other diagnostic output
                lines.append("  Diagnostic Output:")
                for key, value in result.ptp_status.diagnostic_output.items():
                    if key == 'troubleshooting':
                        continue  # Already displayed above
                    # Truncate long diagnostic output
                    truncated_value = value[:200] + "..." if len(value) > 200 else value
                    lines.append(f"    {key}: {truncated_value}")
        
        lines.append("=" * 70)
        return "\n".join(lines)
    
    def generate_summary_report(self, results: List[TestResult]) -> str:
        """
        Generate a summary report aggregating all test results.
        Groups results by instance type and shows individual results for each instance.
        
        Args:
            results: List of TestResult objects from all tests
            
        Returns:
            Formatted summary report with statistics grouped by instance type
        """
        if not results:
            return "No test results to report."
        
        lines = []
        lines.append("=" * 70)
        lines.append("PTP INSTANCE TESTER - SUMMARY REPORT")
        lines.append("=" * 70)
        
        # Calculate summary statistics
        total_instances = len(results)
        ptp_supported = sum(1 for r in results if r.ptp_status.supported)
        ptp_unsupported = total_instances - ptp_supported
        total_duration = sum(r.duration_seconds for r in results)
        
        lines.append(f"\nTotal Instances Tested: {total_instances}")
        lines.append(f"PTP Supported: {ptp_supported}")
        lines.append(f"PTP Unsupported: {ptp_unsupported}")
        lines.append(f"Total Test Duration: {total_duration:.2f} seconds")
        
        # Group results by instance type
        from collections import defaultdict
        results_by_type = defaultdict(list)
        for result in results:
            results_by_type[result.instance_details.instance_type].append(result)
        
        # List all tested instance types with results
        lines.append("\nTest Results by Instance Type:")
        lines.append("-" * 70)
        
        for instance_type, type_results in results_by_type.items():
            # Calculate statistics for this instance type
            type_supported = sum(1 for r in type_results if r.ptp_status.supported)
            type_total = len(type_results)
            
            # Display instance type header with quantity and success rate
            lines.append(f"\n{instance_type} (tested: {type_total}, supported: {type_supported}/{type_total})")
            
            # Display individual results for each instance
            for idx, result in enumerate(type_results, 1):
                status = "✓ SUPPORTED" if result.ptp_status.supported else "✗ NOT SUPPORTED"
                lines.append(f"  Instance {idx}/{type_total}: {status}")
                lines.append(f"    Instance ID: {result.instance_details.instance_id}")
                
                # Include architecture if available
                if result.instance_details.architecture:
                    lines.append(f"    Architecture: {result.instance_details.architecture}")
                
                lines.append(f"    AZ: {result.instance_details.availability_zone}")
                
                # Include placement group if present
                if result.instance_details.placement_group:
                    lines.append(f"    Placement Group: {result.instance_details.placement_group}")
                
                lines.append(f"    Duration: {result.duration_seconds:.2f}s")
                if result.ptp_status.supported and result.ptp_status.clock_device:
                    lines.append(f"    Clock Device: {result.ptp_status.clock_device}")
                lines.append("")
        
        lines.append("=" * 70)
        return "\n".join(lines)
    
    def export_json(self, results: List[TestResult], filepath: str) -> None:
        """
        Export test results to JSON file.
        
        Args:
            results: List of TestResult objects
            filepath: Path to output JSON file
        """
        data = self._results_to_dict(results)
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)
    
    def export_yaml(self, results: List[TestResult], filepath: str) -> None:
        """
        Export test results to YAML file.
        
        Args:
            results: List of TestResult objects
            filepath: Path to output YAML file
        """
        try:
            import yaml
        except ImportError:
            raise ImportError("PyYAML is required for YAML export. Install with: pip install pyyaml")
        
        data = self._results_to_dict(results)
        
        with open(filepath, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    
    def _results_to_dict(self, results: List[TestResult]) -> Dict[str, Any]:
        """
        Convert test results to dictionary format for JSON/YAML export.
        Groups results by instance type and includes instance index.
        
        Args:
            results: List of TestResult objects
            
        Returns:
            Dictionary with test summary and detailed results grouped by instance type
        """
        from collections import defaultdict
        
        # Calculate summary statistics
        total_instances = len(results)
        ptp_supported = sum(1 for r in results if r.ptp_status.supported)
        ptp_unsupported = total_instances - ptp_supported
        total_duration = sum(r.duration_seconds for r in results)
        
        # Group results by instance type
        results_by_type = defaultdict(list)
        for result in results:
            results_by_type[result.instance_details.instance_type].append(result)
        
        # Build results list with instance index
        results_list = []
        for instance_type, type_results in results_by_type.items():
            for idx, r in enumerate(type_results, 1):
                results_list.append({
                    "instance_type": r.instance_details.instance_type,
                    "instance_index": idx,
                    "total_instances_of_type": len(type_results),
                    "instance_id": r.instance_details.instance_id,
                    "architecture": r.instance_details.architecture,
                    "availability_zone": r.instance_details.availability_zone,
                    "subnet_id": r.instance_details.subnet_id,
                    "placement_group": r.instance_details.placement_group,
                    "public_ip": self._sanitize_ip(r.instance_details.public_ip) if r.instance_details.public_ip else None,
                    "private_ip": self._sanitize_ip(r.instance_details.private_ip),
                    "state": r.instance_details.state,
                    "ptp_status": {
                        "supported": r.ptp_status.supported,
                        "ena_driver_version": r.ptp_status.ena_driver_version,
                        "ena_driver_compatible": r.ptp_status.ena_driver_compatible,
                        "hardware_clock_present": r.ptp_status.hardware_clock_present,
                        "ptp_ena_symlink_present": r.ptp_status.ptp_ena_symlink_present,
                        "chrony_using_phc": r.ptp_status.chrony_using_phc,
                        "chrony_synchronized": r.ptp_status.chrony_synchronized,
                        "clock_device": r.ptp_status.clock_device,
                        "time_offset_ns": r.ptp_status.time_offset_ns,
                        "error_message": r.ptp_status.error_message,
                        "diagnostic_output": r.ptp_status.diagnostic_output
                    },
                    "configuration_success": r.configuration_success,
                    "timestamp": r.timestamp.isoformat(),
                    "duration_seconds": round(r.duration_seconds, 2)
                })
        
        return {
            "test_summary": {
                "total_instances": total_instances,
                "ptp_supported": ptp_supported,
                "ptp_unsupported": ptp_unsupported,
                "test_duration_seconds": round(total_duration, 2),
                "instance_types_tested": len(results_by_type)
            },
            "results": results_list
        }
    
    def _sanitize_ip(self, ip_address: str) -> str:
        """
        Sanitize IP address by showing only first two octets.
        
        Args:
            ip_address: Full IP address
            
        Returns:
            Sanitized IP address (e.g., "10.0.x.x")
        """
        parts = ip_address.split('.')
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.x.x"
        return ip_address
