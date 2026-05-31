#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-Device Workflow Orchestration

Parallel device operations using workflow system for:
- Batch calibration testing
- Parallel device health checks
- Concurrent automation execution

Usage:
    python scripts/workflow_multi_device.py check-all
    python scripts/workflow_multi_device.py calibrate-batch --devices device1,device2,device3
    python scripts/workflow_multi_device.py test-all
"""

import sys
import argparse
from pathlib import Path
import yaml

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger

DEVICES_CONFIG = project_root / "config" / "devices.yaml"


def load_devices():
    """Load all devices from configuration."""
    if not DEVICES_CONFIG.exists():
        return []

    with open(DEVICES_CONFIG, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    return config.get('devices', [])


def generate_health_check_workflow(devices):
    """Generate workflow script for parallel device health checks."""

    device_list = [d['phone_id'] for d in devices if d['status'] != 'disabled']

    workflow_script = f"""export const meta = {{
  name: 'multi-device-health-check',
  description: 'Parallel health check for {len(device_list)} devices',
  phases: [
    {{ title: 'Scan Hardware', detail: 'Detect ADB and CH9329 devices' }},
    {{ title: 'Check Devices', detail: 'Test each device in parallel' }},
    {{ title: 'Report', detail: 'Compile health check results' }},
  ],
}}

const devices = {device_list};

phase('Scan Hardware')
log('Scanning for ADB devices and CH9329 controllers...')

const hardwareScan = await agent(
  'Scan all connected ADB devices and COM ports. Return JSON with adb_devices (array of serials) and com_ports (array of port names).',
  {{
    label: 'Hardware scan',
    phase: 'Scan Hardware',
    schema: {{
      type: 'object',
      properties: {{
        adb_devices: {{ type: 'array', items: {{ type: 'string' }} }},
        com_ports: {{ type: 'array', items: {{ type: 'string' }} }},
      }},
      required: ['adb_devices', 'com_ports']
    }}
  }}
)

log(`Found ${{hardwareScan.adb_devices.length}} ADB devices and ${{hardwareScan.com_ports.length}} COM ports`)

phase('Check Devices')
log(`Checking ${{devices.length}} devices in parallel...`)

const deviceChecks = await parallel(
  devices.map(deviceId => async () => {{
    return await agent(
      `Check health of device: ${{deviceId}}. Load config from config/devices.yaml, verify ADB connection, CH9329 port, and calibration profile. Return status object.`,
      {{
        label: `Check ${{deviceId}}`,
        phase: 'Check Devices',
        schema: {{
          type: 'object',
          properties: {{
            device_id: {{ type: 'string' }},
            adb_connected: {{ type: 'boolean' }},
            ch9329_connected: {{ type: 'boolean' }},
            calibrated: {{ type: 'boolean' }},
            ready: {{ type: 'boolean' }},
            issues: {{ type: 'array', items: {{ type: 'string' }} }},
          }},
          required: ['device_id', 'adb_connected', 'ch9329_connected', 'calibrated', 'ready']
        }}
      }}
    )
  }})
)

phase('Report')
log('Compiling health check report...')

const report = await agent(
  `Create a health check report from these device checks: ${{JSON.stringify(deviceChecks)}}.
   Summarize: total devices, ready devices, devices with issues, and recommendations.`,
  {{
    label: 'Generate report',
    phase: 'Report',
    schema: {{
      type: 'object',
      properties: {{
        total_devices: {{ type: 'number' }},
        ready_devices: {{ type: 'number' }},
        devices_with_issues: {{ type: 'number' }},
        summary: {{ type: 'string' }},
        recommendations: {{ type: 'array', items: {{ type: 'string' }} }},
      }},
      required: ['total_devices', 'ready_devices', 'summary']
    }}
  }}
)

log('Health check complete!')
return report
"""

    return workflow_script


def generate_calibration_test_workflow(device_ids):
    """Generate workflow for parallel calibration testing."""

    workflow_script = f"""export const meta = {{
  name: 'multi-device-calibration-test',
  description: 'Test calibration on {len(device_ids)} devices in parallel',
  phases: [
    {{ title: 'Load Profiles', detail: 'Load calibration profiles for each device' }},
    {{ title: 'Test Points', detail: 'Test calibration points in parallel' }},
    {{ title: 'Validate', detail: 'Validate test results' }},
  ],
}}

const deviceIds = {device_ids};

phase('Load Profiles')
log('Loading calibration profiles...')

const profiles = await parallel(
  deviceIds.map(deviceId => async () => {{
    return await agent(
      `Load calibration profile for device: ${{deviceId}}. Read from config/calibration_profiles/${{deviceId}}_default.yaml. Return profile with points array.`,
      {{
        label: `Load ${{deviceId}} profile`,
        phase: 'Load Profiles',
        schema: {{
          type: 'object',
          properties: {{
            device_id: {{ type: 'string' }},
            profile_id: {{ type: 'string' }},
            points_count: {{ type: 'number' }},
            points: {{
              type: 'array',
              items: {{
                type: 'object',
                properties: {{
                  name: {{ type: 'string' }},
                  x: {{ type: 'number' }},
                  y: {{ type: 'number' }},
                }}
              }}
            }},
          }},
          required: ['device_id', 'points_count']
        }}
      }}
    )
  }})
)

log(`Loaded ${{profiles.filter(Boolean).length}} profiles`)

phase('Test Points')
log('Testing calibration points in parallel...')

const testResults = await parallel(
  profiles.filter(Boolean).map(profile => async () => {{
    return await agent(
      `Test calibration points for ${{profile.device_id}}. For each point in ${{JSON.stringify(profile.points)}}, verify coordinates are within screen bounds and ratios are correct. Return test results.`,
      {{
        label: `Test ${{profile.device_id}}`,
        phase: 'Test Points',
        schema: {{
          type: 'object',
          properties: {{
            device_id: {{ type: 'string' }},
            total_points: {{ type: 'number' }},
            valid_points: {{ type: 'number' }},
            invalid_points: {{ type: 'array', items: {{ type: 'string' }} }},
            all_valid: {{ type: 'boolean' }},
          }},
          required: ['device_id', 'total_points', 'valid_points', 'all_valid']
        }}
      }}
    )
  }})
)

phase('Validate')
log('Validating results...')

const validation = await agent(
  `Validate calibration test results: ${{JSON.stringify(testResults)}}.
   Report which devices passed, which failed, and what needs fixing.`,
  {{
    label: 'Validate results',
    phase: 'Validate',
    schema: {{
      type: 'object',
      properties: {{
        passed_devices: {{ type: 'array', items: {{ type: 'string' }} }},
        failed_devices: {{ type: 'array', items: {{ type: 'string' }} }},
        summary: {{ type: 'string' }},
        next_steps: {{ type: 'array', items: {{ type: 'string' }} }},
      }},
      required: ['passed_devices', 'failed_devices', 'summary']
    }}
  }}
)

log('Calibration test complete!')
return validation
"""

    return workflow_script


def generate_batch_automation_workflow(device_ids, flow_id):
    """Generate workflow for parallel automation execution."""

    workflow_script = f"""export const meta = {{
  name: 'multi-device-automation',
  description: 'Execute {flow_id} on {len(device_ids)} devices in parallel',
  phases: [
    {{ title: 'Prepare', detail: 'Load flow and verify devices' }},
    {{ title: 'Execute', detail: 'Run automation on all devices' }},
    {{ title: 'Collect Results', detail: 'Gather execution results' }},
  ],
}}

const deviceIds = {device_ids};
const flowId = '{flow_id}';

phase('Prepare')
log(`Preparing to execute flow: ${{flowId}} on ${{deviceIds.length}} devices...`)

const flowDef = await agent(
  `Load automation flow definition from config/flows/${{flowId}}.yaml. Return flow structure with steps.`,
  {{
    label: 'Load flow',
    phase: 'Prepare',
    schema: {{
      type: 'object',
      properties: {{
        flow_id: {{ type: 'string' }},
        name: {{ type: 'string' }},
        steps_count: {{ type: 'number' }},
      }},
      required: ['flow_id', 'steps_count']
    }}
  }}
)

log(`Flow loaded: ${{flowDef.name}} with ${{flowDef.steps_count}} steps`)

phase('Execute')
log('Executing automation on all devices in parallel...')

const executions = await parallel(
  deviceIds.map(deviceId => async () => {{
    return await agent(
      `Execute automation flow ${{flowId}} on device ${{deviceId}}.
       Simulate execution: load device config, load calibration profile, execute each step.
       Return execution result with success status and any errors.`,
      {{
        label: `Execute on ${{deviceId}}`,
        phase: 'Execute',
        schema: {{
          type: 'object',
          properties: {{
            device_id: {{ type: 'string' }},
            flow_id: {{ type: 'string' }},
            success: {{ type: 'boolean' }},
            steps_completed: {{ type: 'number' }},
            duration_seconds: {{ type: 'number' }},
            error: {{ type: 'string' }},
          }},
          required: ['device_id', 'flow_id', 'success', 'steps_completed']
        }}
      }}
    )
  }})
)

phase('Collect Results')
log('Collecting and analyzing results...')

const results = await agent(
  `Analyze automation execution results: ${{JSON.stringify(executions)}}.
   Report success rate, failed devices, average duration, and recommendations.`,
  {{
    label: 'Analyze results',
    phase: 'Collect Results',
    schema: {{
      type: 'object',
      properties: {{
        total_executions: {{ type: 'number' }},
        successful: {{ type: 'number' }},
        failed: {{ type: 'number' }},
        success_rate: {{ type: 'number' }},
        failed_devices: {{ type: 'array', items: {{ type: 'string' }} }},
        average_duration: {{ type: 'number' }},
        summary: {{ type: 'string' }},
      }},
      required: ['total_executions', 'successful', 'failed', 'success_rate', 'summary']
    }}
  }}
)

log('Automation complete!')
return results
"""

    return workflow_script


def cmd_check_all(args):
    """Run parallel health check on all devices."""
    devices = load_devices()

    if not devices:
        logger.error("No devices configured")
        return 1

    logger.info(f"Generating health check workflow for {len(devices)} devices...")

    workflow_script = generate_health_check_workflow(devices)

    # Save workflow script
    workflow_dir = project_root / ".claude" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)

    script_path = workflow_dir / "multi_device_health_check.js"
    script_path.write_text(workflow_script, encoding='utf-8')

    logger.success(f"Workflow script saved: {script_path}")
    logger.info("\nTo execute this workflow, run:")
    logger.info(f"  Workflow({{scriptPath: '{script_path}'}})")

    return 0


def cmd_calibrate_batch(args):
    """Test calibration on multiple devices in parallel."""
    if not args.devices:
        logger.error("No devices specified. Use --devices device1,device2,device3")
        return 1

    device_ids = [d.strip() for d in args.devices.split(',')]

    logger.info(f"Generating calibration test workflow for {len(device_ids)} devices...")

    workflow_script = generate_calibration_test_workflow(device_ids)

    # Save workflow script
    workflow_dir = project_root / ".claude" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)

    script_path = workflow_dir / "multi_device_calibration_test.js"
    script_path.write_text(workflow_script, encoding='utf-8')

    logger.success(f"Workflow script saved: {script_path}")
    logger.info("\nTo execute this workflow, run:")
    logger.info(f"  Workflow({{scriptPath: '{script_path}'}})")

    return 0


def cmd_test_all(args):
    """Run automation test on all devices in parallel."""
    devices = load_devices()
    active_devices = [d for d in devices if d['status'] != 'disabled']

    if not active_devices:
        logger.error("No active devices found")
        return 1

    device_ids = [d['phone_id'] for d in active_devices]
    flow_id = args.flow or 'test_basic_navigation'

    logger.info(f"Generating automation workflow for {len(device_ids)} devices...")
    logger.info(f"Flow: {flow_id}")

    workflow_script = generate_batch_automation_workflow(device_ids, flow_id)

    # Save workflow script
    workflow_dir = project_root / ".claude" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)

    script_path = workflow_dir / "multi_device_automation.js"
    script_path.write_text(workflow_script, encoding='utf-8')

    logger.success(f"Workflow script saved: {script_path}")
    logger.info("\nTo execute this workflow, run:")
    logger.info(f"  Workflow({{scriptPath: '{script_path}'}})")

    return 0


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Multi-Device Workflow Orchestration',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Check all devices in parallel:
    python scripts/workflow_multi_device.py check-all

  Test calibration on specific devices:
    python scripts/workflow_multi_device.py calibrate-batch --devices vivo_001,vivo_002,pixel_001

  Run automation on all devices:
    python scripts/workflow_multi_device.py test-all --flow test_basic_navigation
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # check-all command
    subparsers.add_parser('check-all', help='Parallel health check on all devices')

    # calibrate-batch command
    parser_calibrate = subparsers.add_parser('calibrate-batch', help='Test calibration on multiple devices')
    parser_calibrate.add_argument('--devices', required=True, help='Comma-separated device IDs')

    # test-all command
    parser_test = subparsers.add_parser('test-all', help='Run automation on all devices')
    parser_test.add_argument('--flow', help='Flow ID to execute (default: test_basic_navigation)')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Execute command
    commands = {
        'check-all': cmd_check_all,
        'calibrate-batch': cmd_calibrate_batch,
        'test-all': cmd_test_all,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
