#!/usr/bin/env python3

import subprocess
import datetime
import time
import re
import os
import json
import threading

class EmulatorEventRecorder:
    def __init__(self):
        self.device_id = "emulator-5554"
        self.json_output_file = "emulator_events.json"
        self.coords = {'x': None, 'y': None}
        self.current_pkg = "unknown"
        self.current_activity = "unknown"
        self.current_device = "unknown"
        self.all_device_paths = []
        self.pending_events = {}
        self.current_view_hierarchy = []
        self.last_hierarchy_update = 0
        self.event_counter = 0
        self.buffer_timeout = 0.1  # Buffer events for 100ms to ensure complete data
    
    def setup(self):
        """Setup recorder for emulator-5554."""
        # Check if emulator is connected
        if not self._check_emulator_connected():
            print(f"Emulator {self.device_id} not found. Please start the emulator.")
            return False
            
        # Get all input devices from emulator
        self.all_device_paths = self._get_all_input_devices()
        if not self.all_device_paths:
            print("No input devices found on emulator.")
            return False
            
        print(f"Found {len(self.all_device_paths)} input devices on emulator-5554")
        
        # Get Android version
        self.android_version = self._get_android_version()
        print(f"Android SDK version: {self.android_version}")
        
        # Get initial app info
        self.current_pkg, self.current_activity = self._get_current_app_info()
        print(f"Current app: {self.current_pkg}/{self.current_activity}")
        
        # Initial view hierarchy update
        self._update_view_hierarchy()
        
        # Initialize JSON output file (overwrite if exists)
        with open(self.json_output_file, 'w') as f:
            f.write('[\n')  # Start JSON array
        
        return True
        
    def start_recording(self):
        """Start recording all events from all input devices."""
        if not self.all_device_paths or not self.json_output_file:
            print("Recorder not properly set up.")
            return
        
        print(f"\nRecording ALL events from emulator-5554")
        print("Press Ctrl+C to stop recording...\n")
        
        # Start buffer processing thread
        buffer_thread = threading.Thread(target=self._process_buffer)
        buffer_thread.daemon = True
        buffer_thread.start()
        
        try:
            # Command to capture all events
            if self.android_version >= 23:
                cmd = f"adb -s {self.device_id} exec-out getevent -lt"
            else:
                cmd = f"adb -s {self.device_id} shell getevent -lt"
                
            # Start process
            process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Process events in real-time
            for line in iter(process.stdout.readline, b''):
                line_str = line.decode('utf-8', errors='replace').strip()
                self._collect_event_data(line_str)
                
        except KeyboardInterrupt:
            print("\nStopping recording...")
            
        finally:
            if 'process' in locals():
                process.terminate()
            
            # Allow buffer to process remaining events
            time.sleep(0.5)
            
            # Close JSON array
            with open(self.json_output_file, 'a') as f:
                f.write('\n]')
                
            print(f"\nRecording stopped. Events saved to: {self.json_output_file}")
    
    def _collect_event_data(self, line):
        """Collect event data for buffering."""
        # Extract device path
        if line.startswith("/dev/input/"):
            self.current_device = line.strip(":")
            return
        
        # Extract event info
        event_info = self._parse_event(line)
        
        # Update coordinates if found
        if 'x' in event_info:
            self.coords['x'] = event_info['x']
        if 'y' in event_info:
            self.coords['y'] = event_info['y']
        
        # For event types, store in pending events with current time
        if 'event_type' in event_info:
            timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            event_id = f"{timestamp}_{event_info['event_type']}_{self.current_device}"
            
            # Create or update pending event
            if event_id not in self.pending_events:
                self.pending_events[event_id] = {
                    "timestamp": timestamp,
                    "device": self.current_device,
                    "package": self.current_pkg,
                    "activity": self.current_activity,
                    "event_type": event_info['event_type'],
                    "coordinates": {
                        "x": self.coords['x'],
                        "y": self.coords['y']
                    },
                    "created_at": time.time(),
                    "resource_id": "unknown",
                    "extra_info": event_info.get('extra_info', '')
                }
            else:
                # Update with latest coordinates
                self.pending_events[event_id]["coordinates"]["x"] = self.coords['x']
                self.pending_events[event_id]["coordinates"]["y"] = self.coords['y']
                self.pending_events[event_id]["created_at"] = time.time()
                if 'extra_info' in event_info:
                    self.pending_events[event_id]["extra_info"] = event_info['extra_info']
            
            # Sync event for certain types
            if event_info['event_type'] in ["MOTION", "TOUCH_UP"]:
                # Update app and view info for touch events
                self.current_pkg, self.current_activity = self._get_current_app_info()
                if time.time() - self.last_hierarchy_update > 0.3:  # Limit updates to avoid slowdown
                    self._update_view_hierarchy()
                    self.last_hierarchy_update = time.time()
    
    def _process_buffer(self):
        """Process buffered events in a separate thread."""
        while True:
            current_time = time.time()
            events_to_remove = []
            
            # Process events that are complete or older than buffer timeout
            for event_id, event in self.pending_events.items():
                age = current_time - event["created_at"]
                
                # Complete event has coordinates and is ready to process
                is_complete = (event["coordinates"]["x"] is not None and 
                               event["coordinates"]["y"] is not None)
                               
                # Process if complete or older than buffer timeout
                if is_complete or age > self.buffer_timeout:
                    # Find resource at coordinates if available
                    if is_complete:
                        event["resource_id"] = self._find_resource_at_coordinates(
                            event["coordinates"]["x"], 
                            event["coordinates"]["y"]
                        )
                    
                    # Create JSON object without internal tracking fields
                    json_obj = event.copy()
                    json_obj.pop("created_at", None)
                    json_obj["event_id"] = self.event_counter
                    
                    # Write to JSON file
                    with open(self.json_output_file, 'a') as f:
                        if self.event_counter > 0:
                            f.write(',\n')
                        f.write(json.dumps(json_obj, indent=2))
                    
                    # Print to console
                    print(f"{event['timestamp']} | {event['device']} | {event['package']}/{event['activity']} | " +
                          f"{event['event_type']} | X:{event['coordinates']['x']} Y:{event['coordinates']['y']} | " +
                          f"{event['resource_id']} | {event['extra_info']}")
                    
                    self.event_counter += 1
                    events_to_remove.append(event_id)
            
            # Remove processed events
            for event_id in events_to_remove:
                self.pending_events.pop(event_id, None)
            
            # Sleep to avoid high CPU usage
            time.sleep(0.05)
    
    def _parse_event(self, line):
        """Parse event line and extract information."""
        event_info = {}
        
        # Touch position X
        if "ABS_MT_POSITION_X" in line or "ABS_X" in line:
            try:
                value = line.split()[-1]
                if value.startswith("0x"):
                    event_info['x'] = int(value[2:], 16)
                else:
                    event_info['x'] = int(value)
            except (ValueError, IndexError):
                pass
                
        # Touch position Y
        elif "ABS_MT_POSITION_Y" in line or "ABS_Y" in line:
            try:
                value = line.split()[-1]
                if value.startswith("0x"):
                    event_info['y'] = int(value[2:], 16)
                else:
                    event_info['y'] = int(value)
            except (ValueError, IndexError):
                pass
        
        # Touch pressure
        elif "ABS_MT_PRESSURE" in line or "ABS_PRESSURE" in line:
            try:
                value = line.split()[-1]
                if value.startswith("0x"):
                    pressure = int(value[2:], 16)
                else:
                    pressure = int(value)
                event_info['extra_info'] = f"Pressure:{pressure}"
            except (ValueError, IndexError):
                pass
        
        # Button events
        elif "BTN_TOUCH" in line:
            if "DOWN" in line:
                event_info['event_type'] = "TOUCH_DOWN"
            elif "UP" in line:
                event_info['event_type'] = "TOUCH_UP"
                
        # Multi-touch tracking
        elif "ABS_MT_TRACKING_ID" in line:
            value = line.split()[-1]
            if "ffffffff" in value:
                event_info['event_type'] = "TOUCH_UP"
            else:
                event_info['event_type'] = "TOUCH_DOWN"
                try:
                    if value.startswith("0x"):
                        track_id = int(value[2:], 16)
                    else:
                        track_id = int(value)
                    event_info['extra_info'] = f"TrackID:{track_id}"
                except (ValueError, IndexError):
                    pass
                    
        # Synchronization event (indicates a complete input event)
        elif "EV_SYN SYN_REPORT" in line:
            event_info['event_type'] = "MOTION"
            
        # Key events
        elif "EV_KEY" in line:
            if "KEY_" in line:
                key_match = re.search(r'KEY_(\w+)', line)
                if key_match:
                    key_name = key_match.group(1)
                    if "DOWN" in line:
                        event_info['event_type'] = "KEY_DOWN"
                    elif "UP" in line:
                        event_info['event_type'] = "KEY_UP"
                    event_info['extra_info'] = f"Key:{key_name}"
            
        return event_info
    
    def _update_view_hierarchy(self):
        """Update the current view hierarchy to get resource IDs."""
        try:
            # Use UI Automator to dump view hierarchy
            subprocess.run(
                f'adb -s {self.device_id} shell uiautomator dump /sdcard/window_dump.xml',
                shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1
            )
            
            subprocess.run(
                f'adb -s {self.device_id} pull /sdcard/window_dump.xml /tmp/window_dump.xml',
                shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1
            )
            
            # Parse XML to extract view info
            if os.path.exists('/tmp/window_dump.xml'):
                with open('/tmp/window_dump.xml', 'r') as f:
                    xml_content = f.read()
                
                # Extract node info with bounds and resource-id
                self.current_view_hierarchy = []
                for node_match in re.finditer(r'<node[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*?(resource-id="([^"]*)")?', xml_content):
                    groups = node_match.groups()
                    x1, y1, x2, y2 = int(groups[0]), int(groups[1]), int(groups[2]), int(groups[3])
                    resource_id = groups[5] if groups[5] else "no-id"
                    
                    self.current_view_hierarchy.append({
                        'x1': x1,
                        'y1': y1,
                        'x2': x2,
                        'y2': y2,
                        'resource_id': resource_id,
                        'text': self._extract_text_from_node(node_match.group(0)),
                        'class': self._extract_class_from_node(node_match.group(0))
                    })
        except Exception as e:
            # Silent fail to avoid interrupting recording
            pass
    
    def _extract_text_from_node(self, node_str):
        """Extract text attribute from node string."""
        text_match = re.search(r'text="([^"]*)"', node_str)
        if text_match:
            return text_match.group(1)
        return ""
    
    def _extract_class_from_node(self, node_str):
        """Extract class attribute from node string."""
        class_match = re.search(r'class="([^"]*)"', node_str)
        if class_match:
            return class_match.group(1)
        return ""
    
    def _find_resource_at_coordinates(self, x, y):
        """Find resource ID at the given coordinates."""
        if x is None or y is None:
            return "unknown"
            
        matching_nodes = []
        
        for node in self.current_view_hierarchy:
            if node['x1'] <= x <= node['x2'] and node['y1'] <= y <= node['y2']:
                matching_nodes.append(node)
        
        # Return the smallest (most specific) node
        if matching_nodes:
            smallest_node = min(matching_nodes, key=lambda n: (n['x2'] - n['x1']) * (n['y2'] - n['y1']))
            resource_info = smallest_node['resource_id']
            
            # Add text if available
            text_info = ""
            if smallest_node['text']:
                text_info = f" ('{smallest_node['text']}')"
            
            # Add class if available and no resource ID
            if resource_info == "no-id" and smallest_node['class']:
                class_name = smallest_node['class'].split('.')[-1]  # Get just the class name without package
                return f"{class_name}{text_info}"
            
            return f"{resource_info}{text_info}"
        
        return "unknown"
    
    def _check_emulator_connected(self):
        """Check if emulator-5554 is connected."""
        result = subprocess.run(['adb', 'devices'], capture_output=True, text=True)
        return self.device_id in result.stdout
    
    def _get_all_input_devices(self):
        """Get all input device paths from emulator."""
        result = subprocess.run(f'adb -s {self.device_id} shell ls /dev/input/', 
                               shell=True, capture_output=True, text=True)
        
        devices = []
        for line in result.stdout.split():
            if line.startswith('event'):
                devices.append(f"/dev/input/{line}")
        
        return devices
    
    def _get_android_version(self):
        """Get Android SDK version."""
        try:
            result = subprocess.run(f'adb -s {self.device_id} shell getprop ro.build.version.sdk', 
                                    shell=True, capture_output=True, text=True)
            version = int(result.stdout.strip())
            return version
        except (ValueError, subprocess.SubprocessError):
            return 0
    
    def _get_current_app_info(self):
        """Get current foreground package and activity."""
        try:
            # Try dumpsys window first (most reliable)
            result = subprocess.run(f'adb -s {self.device_id} shell dumpsys window | grep -E "mCurrentFocus"', 
                                    shell=True, capture_output=True, text=True, timeout=1)
            output = result.stdout
            
            match = re.search(r'mCurrentFocus=.*\{([^/]+)/([^}]+)', output)
            if match:
                return match.group(1), match.group(2)
                
            # If that fails, try dumpsys activity
            result = subprocess.run(f'adb -s {self.device_id} shell dumpsys activity activities | grep -E "mResumedActivity"', 
                                    shell=True, capture_output=True, text=True, timeout=1)
            output = result.stdout
            
            match = re.search(r'mResumedActivity.*\{[^/]+/([^/]+)/([^}]+)', output)
            if match:
                return match.group(1), match.group(2)
        except (subprocess.SubprocessError, subprocess.TimeoutExpired):
            pass
            
        return self.current_pkg, self.current_activity  # Return previous values if update fails

if __name__ == "__main__":
    recorder = EmulatorEventRecorder()
    if recorder.setup():
        recorder.start_recording()