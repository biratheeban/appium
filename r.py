#!/usr/bin/env python3

import subprocess
import datetime
import time
import re
import os
import json
import threading
import signal
import xml.etree.ElementTree as ET

class EmulatorEventRecorder:
    def __init__(self):
        self.device_id = "emulator-5554"
        self.json_output_file = "emulator_events.json"
        self.current_device = "unknown"
        self.all_device_paths = []
        self.pending_events = {}
        self.current_view_hierarchy = []
        self.last_hierarchy_update = 0
        self.event_counter = 0
        self.buffer_timeout = 0.1
        self.running = True
        self.current_pkg = "unknown"
        self.current_activity = "unknown"
        self.last_known_pkg = "unknown"
        self.last_known_activity = "unknown"
        self.update_hierarchy_needed = False
    
    def setup(self):
        """Setup recorder for emulator-5554."""
        if not self._check_emulator_connected():
            print(f"Emulator {self.device_id} not found. Please start the emulator.")
            return False
            
        self.all_device_paths = self._get_all_input_devices()
        if not self.all_device_paths:
            print("No input devices found on emulator.")
            return False
            
        print(f"Found {len(self.all_device_paths)} input devices on emulator-5554")
        
        self.android_version = self._get_android_version()
        print(f"Android SDK version: {self.android_version}")
        
        self.current_pkg, self.current_activity = self._get_current_app_info()
        self.last_known_pkg = self.current_pkg
        self.last_known_activity = self.current_activity
        print(f"Current app: {self.current_pkg}/{self.current_activity}")
        
        signal.signal(signal.SIGINT, self._signal_handler)
        
        with open(self.json_output_file, 'w') as f:
            f.write('[\n')
        
        return True
    
    def _signal_handler(self, sig, frame):
        """Handle Ctrl+C signal"""
        print("\nStopping recording...")
        self.running = False
        
    def start_recording(self):
        """Start recording all events from all input devices."""
        if not self.all_device_paths or not self.json_output_file:
            print("Recorder not properly set up.")
            return
        
        print(f"\nRecording ALL events from emulator-5554")
        print("Press Ctrl+C to stop recording...\n")
        
        buffer_thread = threading.Thread(target=self._process_buffer)
        buffer_thread.daemon = True
        buffer_thread.start()
        
        try:
            cmd = f"adb -s {self.device_id} exec-out getevent -lt" if self.android_version >= 23 else f"adb -s {self.device_id} shell getevent -lt"
            process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            while self.running:
                line = process.stdout.readline()
                if not line:
                    time.sleep(0.01)
                    continue
                    
                line_str = line.decode('utf-8', errors='replace').strip()
                self._collect_event_data(line_str)
                
        finally:
            if 'process' in locals() and process:
                process.terminate()
            
            time.sleep(0.5)
            
            try:
                with open(self.json_output_file, 'a') as f:
                    f.write('\n]')
            except Exception as e:
                print(f"Error closing JSON file: {e}")
                
            print(f"\nRecording stopped. Events saved to: {self.json_output_file}")
    
    def _collect_event_data(self, line):
        """Collect event data for buffering with per-event coordinates."""
        try:
            if line.startswith("/dev/input/"):
                self.current_device = line.strip(":")
                return
            
            event_info = self._parse_event(line)
            timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            event_id = f"{timestamp}_{event_info.get('event_type', 'UNKNOWN')}_{self.current_device}"
            
            # Initialize or update pending event
            if event_id not in self.pending_events:
                self.pending_events[event_id] = {
                    "timestamp": timestamp,
                    "device": self.current_device,
                    "package": self.current_pkg,
                    "activity": self.current_activity,
                    "event_type": event_info.get('event_type', 'UNKNOWN'),
                    "coordinates": {"x": None, "y": None},  # Per-event coordinates
                    "created_at": time.time(),
                    "resource_id": "unknown",
                    "extra_info": ""
                }
            
            # Update coordinates and other info for this event
            event = self.pending_events[event_id]
            if 'x' in event_info:
                event["coordinates"]["x"] = event_info['x']
            if 'y' in event_info:
                event["coordinates"]["y"] = event_info['y']
            if 'extra_info' in event_info:
                event["extra_info"] = event_info['extra_info']
            if 'event_type' in event_info:
                event["event_type"] = event_info['event_type']
                
                # Update app info on significant events
                if event["event_type"] in ["TOUCH_DOWN", "KEY_DOWN"]:
                    try:
                        pkg, activity = self._get_current_app_info()
                        if pkg != "unknown":
                            self.current_pkg = pkg
                            event["package"] = pkg
                        if activity != "unknown":
                            self.current_activity = activity
                            event["activity"] = activity
                        if pkg != self.last_known_pkg or activity != self.last_known_activity:
                            self.update_hierarchy_needed = True
                            self.last_known_pkg = pkg
                            self.last_known_activity = activity
                    except Exception:
                        pass
                
        except Exception as e:
            print(f"Error processing event line: {e}")
    
    def _process_buffer(self):
        """Process buffered events in a separate thread."""
        while self.running:
            try:
                current_time = time.time()
                events_to_remove = []
                
                if self.update_hierarchy_needed:
                    try:
                        self._update_view_hierarchy()
                        self.last_hierarchy_update = current_time
                        self.update_hierarchy_needed = False
                    except Exception as e:
                        print(f"Immediate view hierarchy update failed: {e}")
                
                if (current_time - self.last_hierarchy_update) > 1.0:
                    try:
                        self._update_view_hierarchy()
                        self.last_hierarchy_update = current_time
                    except Exception as e:
                        print(f"Periodic view hierarchy update failed: {e}")
                
                for event_id, event in list(self.pending_events.items()):
                    age = current_time - event["created_at"]
                    
                    if age > self.buffer_timeout:
                        try:
                            if event["coordinates"]["x"] is not None and event["coordinates"]["y"] is not None:
                                event["resource_id"] = self._find_resource_at_coordinates(
                                    event["coordinates"]["x"], 
                                    event["coordinates"]["y"]
                                )
                        except Exception:
                            pass
                        
                        json_obj = event.copy()
                        json_obj.pop("created_at", None)
                        json_obj["event_id"] = self.event_counter
                        
                        try:
                            with open(self.json_output_file, 'a') as f:
                                if self.event_counter > 0:
                                    f.write(',\n')
                                f.write(json.dumps(json_obj, indent=2))
                        except Exception as e:
                            print(f"Error writing to JSON: {e}")
                        
                        print(f"{event['timestamp']} | {event['device']} | {event['package']}/{event['activity']} | " +
                              f"{event['event_type']} | X:{event['coordinates']['x']} Y:{event['coordinates']['y']} | " +
                              f"{event['resource_id']} | {event['extra_info']}")
                        
                        self.event_counter += 1
                        events_to_remove.append(event_id)
                
                for event_id in events_to_remove:
                    self.pending_events.pop(event_id, None)
                
                time.sleep(0.05)
            except Exception as e:
                print(f"Error in buffer processing: {e}")
                time.sleep(0.5)
    
    def _parse_event(self, line):
        """Parse event line and extract information."""
        event_info = {}
        try:
            if "ABS_MT_POSITION_X" in line or "ABS_X" in line:
                value = line.split()[-1]
                event_info['x'] = int(value[2:], 16) if value.startswith("0x") else int(value)
            elif "ABS_MT_POSITION_Y" in line or "ABS_Y" in line:
                value = line.split()[-1]
                event_info['y'] = int(value[2:], 16) if value.startswith("0x") else int(value)
            elif "ABS_MT_PRESSURE" in line or "ABS_PRESSURE" in line:
                value = line.split()[-1]
                pressure = int(value[2:], 16) if value.startswith("0x") else int(value)
                event_info['extra_info'] = f"Pressure:{pressure}"
            elif "BTN_TOUCH" in line:
                event_info['event_type'] = "TOUCH_DOWN" if "DOWN" in line else "TOUCH_UP"
            elif "ABS_MT_TRACKING_ID" in line:
                value = line.split()[-1]
                if "ffffffff" in value:
                    event_info['event_type'] = "TOUCH_UP"
                else:
                    event_info['event_type'] = "TOUCH_DOWN"
                    track_id = int(value[2:], 16) if value.startswith("0x") else int(value)
                    event_info['extra_info'] = f"TrackID:{track_id}"
            elif "EV_SYN SYN_REPORT" in line:
                event_info['event_type'] = "MOTION"
            elif "EV_KEY" in line and "KEY_" in line:
                key_match = re.search(r'KEY_(\w+)', line)
                if key_match:
                    key_name = key_match.group(1)
                    event_info['event_type'] = "KEY_DOWN" if "DOWN" in line else "KEY_UP"
                    event_info['extra_info'] = f"Key:{key_name}"
        except Exception as e:
            print(f"Error parsing event: {e}")
        return event_info
    
    def _update_view_hierarchy(self):
        """Update the current view hierarchy using ElementTree parsing."""
        adb_timeout = 5
        try:
            subprocess.run(
                f'adb -s {self.device_id} shell rm /sdcard/window_dump.xml',
                shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1
            )
            result = subprocess.run(
                f'adb -s {self.device_id} shell uiautomator dump /sdcard/window_dump.xml',
                shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=adb_timeout
            )
            if result.stdout and "UI hierchary dumped to" in result.stdout.decode('utf-8', errors='replace') or not result.stderr:
                subprocess.run(
                    f'adb -s {self.device_id} pull /sdcard/window_dump.xml /tmp/window_dump.xml',
                    shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=adb_timeout
                )
                if os.path.exists('/tmp/window_dump.xml'):
                    try:
                        with open('/tmp/window_dump.xml', 'r') as f:
                            root = ET.parse(f).getroot()
                        self.current_view_hierarchy = []
                        for node in root.findall('.//node'):
                            bounds_str = node.get('bounds')
                            if bounds_str:
                                bounds_match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds_str)
                                if bounds_match:
                                    x1, y1, x2, y2 = map(int, bounds_match.groups())
                                    self.current_view_hierarchy.append({
                                        'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
                                        'resource_id': node.get('resource-id', ''),
                                        'content_desc': node.get('content-desc', ''),
                                        'text': node.get('text', ''),
                                        'class': node.get('class', ''),
                                        'package': node.get('package', '')
                                    })
                    except Exception as e:
                        print(f"Error parsing XML: {e}")
        except subprocess.TimeoutExpired:
            print(f"Warning: UI Automator dump timeout (> {adb_timeout}s), using previous hierarchy")
        except Exception as e:
            print(f"Warning: View hierarchy update failed: {e}")
    
    def _find_resource_at_coordinates(self, x, y):
        """Find resource ID at the given coordinates."""
        if x is None or y is None or not self.current_view_hierarchy:
            return "unknown"
            
        matching_nodes = [node for node in self.current_view_hierarchy if node['x1'] <= x <= node['x2'] and node['y1'] <= y <= node['y2']]
        
        if matching_nodes:
            smallest_node = min(matching_nodes, key=lambda n: (n['x2'] - n['x1']) * (n['y2'] - n['y1']))
            if smallest_node['resource_id']:
                return smallest_node['resource_id']
            if smallest_node['content_desc']:
                return f"{smallest_node['class']} '{smallest_node['content_desc']}'"
            if smallest_node['text']:
                return f"{smallest_node['class']} '{smallest_node['text']}'"
            if smallest_node['class']:
                return smallest_node['class'].split('.')[-1]
        
        return "unknown"
    
    def _check_emulator_connected(self):
        """Check if emulator-5554 is connected."""
        try:
            result = subprocess.run(['adb', 'devices'], capture_output=True, text=True, timeout=5)
            return self.device_id in result.stdout
        except Exception:
            return False
    
    def _get_all_input_devices(self):
        """Get all input device paths from emulator."""
        try:
            result = subprocess.run(f'adb -s {self.device_id} shell ls /dev/input/', 
                                  shell=True, capture_output=True, text=True, timeout=5)
            return [f"/dev/input/{line}" for line in result.stdout.split() if line.startswith('event')]
        except Exception:
            return []
    
    def _get_android_version(self):
        """Get Android SDK version."""
        try:
            result = subprocess.run(f'adb -s {self.device_id} shell getprop ro.build.version.sdk', 
                                  shell=True, capture_output=True, text=True, timeout=5)
            return int(result.stdout.strip())
        except Exception:
            return 0
    
    def _get_current_app_info(self):
        """Get current foreground package and activity."""
        try:
            result = subprocess.run(f'adb -s {self.device_id} shell dumpsys window | grep -E "mCurrentFocus"', 
                                shell=True, capture_output=True, text=True, timeout=3)
            output = result.stdout
            match = re.search(r'mCurrentFocus=.*\{[^ ]+ ([^ ]+) ([^/]+)/([^}]+)', output)
            if match and match.group(2) != "u0":
                return match.group(2), match.group(3)
            match = re.search(r'mCurrentFocus=.*\{[^ ]+ [^ ]+ ([^/]+)/([^}]+)', output)
            if match:
                return match.group(1), match.group(2)
            match = re.search(r'mCurrentFocus=.*\{[^ ]+ ([^/]+)/([^}]+)', output)
            if match:
                return match.group(1), match.group(2)
            result = subprocess.run(f'adb -s {self.device_id} shell dumpsys activity activities | grep -E "mResumedActivity"', 
                                shell=True, capture_output=True, text=True, timeout=3)
            output = result.stdout
            match = re.search(r'mResumedActivity.*\{[^/]+/([^/]+)/([^}]+)', output)
            if match:
                return match.group(1), match.group(2)
        except Exception as e:
            print(f"Error getting app info: {e}")
        return self.current_pkg, self.current_activity

if __name__ == "__main__":
    recorder = EmulatorEventRecorder()
    if recorder.setup():
        recorder.start_recording()