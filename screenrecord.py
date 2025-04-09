
import json
import os
import re
import subprocess
import time
import datetime
import threading
import signal

# Device ID
DEVICE_ID = "emulator-5556"

class DirectRecorder:
    def __init__(self, device_id):
        self.device_id = device_id
        self.interactions = []
        self.timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = f"android_recordings_{self.timestamp}"
        self.running = False
        
        # Create output directory
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
    
    def check_device_connection(self):
        """Check if the specified device is connected."""
        result = subprocess.run(
            ["adb", "devices"], 
            capture_output=True, 
            text=True
        )
        
        if self.device_id not in result.stdout:
            raise ConnectionError(f"Device {self.device_id} not found. Connected devices: {result.stdout}")
        
        print(f"Device {self.device_id} found.")
        return True
    
    def capture_screenshot(self, index):
        """Capture a screenshot and save it."""
        screenshot_path = os.path.join(self.output_dir, f"screen_{index:04d}.png")
        
        # Capture screenshot using ADB
        subprocess.run(
            ["adb", "-s", self.device_id, "shell", "screencap", "-p", "/sdcard/screen.png"],
            capture_output=True
        )
        
        # Pull screenshot from device
        subprocess.run(
            ["adb", "-s", self.device_id, "pull", "/sdcard/screen.png", screenshot_path],
            capture_output=True
        )
        
        return screenshot_path
    
    def get_ui_dump(self):
        """Get a UI hierarchy dump."""
        # Dump UI hierarchy to device
        subprocess.run(
            ["adb", "-s", self.device_id, "shell", "uiautomator", "dump", "/sdcard/uidump.xml"],
            capture_output=True
        )
        
        # Pull the dump
        result = subprocess.run(
            ["adb", "-s", self.device_id, "shell", "cat", "/sdcard/uidump.xml"],
            capture_output=True,
            text=True
        )
        
        return result.stdout
    
    def parse_ui_elements(self, ui_dump):
        """Parse UI elements from XML dump."""
        elements = []
        
        # Extract node information using regex
        pattern = r'<node.*?bounds="(\[.*?\])".*?class="(.*?)".*?package="(.*?)".*?text="(.*?)".*?resource-id="(.*?)".*?/>|<node.*?bounds="(\[.*?\])".*?class="(.*?)".*?package="(.*?)".*?resource-id="(.*?)".*?text="(.*?)".*?/>'
        
        for match in re.finditer(pattern, ui_dump):
            # Handle both order variations in the XML
            if match.group(1):  # First pattern match
                bounds = match.group(1)
                class_name = match.group(2)
                package_name = match.group(3)
                text = match.group(4)
                resource_id = match.group(5)
            else:  # Second pattern match
                bounds = match.group(6)
                class_name = match.group(7)
                package_name = match.group(8)
                resource_id = match.group(9)
                text = match.group(10)
            
            # Parse bounds [x1,y1][x2,y2]
            bounds_match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
            if bounds_match:
                x1, y1, x2, y2 = map(int, bounds_match.groups())
                
                element = {
                    "class": class_name,
                    "package": package_name,
                    "text": text,
                    "resource_id": resource_id,
                    "bounds": {
                        "x1": x1,
                        "y1": y1,
                        "x2": x2,
                        "y2": y2,
                        "center_x": (x1 + x2) // 2,
                        "center_y": (y1 + y2) // 2,
                        "width": x2 - x1,
                        "height": y2 - y1
                    }
                }
                
                elements.append(element)
        
        return elements
    
    def get_focused_window(self):
        """Get the currently focused window/app."""
        result = subprocess.run(
            ["adb", "-s", self.device_id, "shell", "dumpsys", "window", "windows", "|", "grep", "-E", "'mCurrentFocus|mFocusedApp'"],
            shell=True,
            capture_output=True,
            text=True
        )
        
        window_info = {}
        
        for line in result.stdout.splitlines():
            if "mCurrentFocus" in line:
                match = re.search(r'mCurrentFocus=Window{.*\s+([^/\s]+)/([^\s}]+)', line)
                if match:
                    window_info["package_name"] = match.group(1)
                    window_info["activity_name"] = match.group(2)
        
        return window_info
    
    def capture_ui_state(self, index, timestamp):
        """Capture the full UI state."""
        screenshot_path = self.capture_screenshot(index)
        ui_dump = self.get_ui_dump()
        ui_elements = self.parse_ui_elements(ui_dump)
        window_info = self.get_focused_window()
        
        ui_state = {
            "index": index,
            "timestamp": timestamp,
            "screenshot": os.path.basename(screenshot_path),
            "window_info": window_info,
            "elements_count": len(ui_elements),
            "ui_elements": ui_elements
        }
        
        return ui_state
    
    def record_interaction(self, event_type, details=None):
        """Record an interaction event."""
        timestamp = time.time()
        
        interaction = {
            "event_type": event_type,
            "timestamp": timestamp,
            "details": details or {}
        }
        
        window_info = self.get_focused_window()
        interaction.update(window_info)
        
        self.interactions.append(interaction)
        
        return interaction
    
    def monitor_touch_events(self):
        """Monitor and record touch events."""
        # Start ADB touch monitoring
        cmd = ["adb", "-s", self.device_id, "shell", "getevent", "-lt", "/dev/input/event1"]
        
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            print("Touch event monitoring started (this may not work on all emulators)")
            
            while self.running:
                line = process.stdout.readline()
                if not line:
                    break
                    
                # Process event line
                if "ABS_MT_POSITION_X" in line:
                    # Extract X position
                    value_match = re.search(r'value ([0-9a-f]+)', line)
                    if value_match:
                        x_value = int(value_match.group(1), 16)
                        self.record_interaction("TOUCH_X", {"x": x_value})
        
        except Exception as e:
            print(f"Error in touch monitoring: {e}")
        finally:
            if process:
                process.terminate()
    
    def poll_ui_changes(self):
        """Poll for UI changes periodically."""
        index = 0
        last_ui_dump = None
        
        print("UI change monitoring started")
        
        while self.running:
            try:
                # Capture current UI dump for comparison
                current_ui_dump = self.get_ui_dump()
                window_info = self.get_focused_window()
                
                # Check if UI changed significantly
                ui_changed = (last_ui_dump is None or 
                             current_ui_dump != last_ui_dump)
                
                if ui_changed:
                    timestamp = time.time()
                    
                    # Capture full state
                    ui_state = self.capture_ui_state(index, timestamp)
                    
                    # Record UI change event
                    self.record_interaction("UI_CHANGE", {
                        "state_index": index,
                        "elements_count": ui_state["elements_count"]
                    })
                    
                    # Save UI state to a JSON file
                    ui_state_file = os.path.join(self.output_dir, f"state_{index:04d}.json")
                    with open(ui_state_file, "w") as f:
                        json.dump(ui_state, f, indent=2)
                    
                    print(f"Recorded UI state {index}: {window_info.get('package_name', 'Unknown')} - {ui_state['elements_count']} elements")
                    
                    # Update for next iteration
                    last_ui_dump = current_ui_dump
                    index += 1
                
                # Sleep before next poll
                time.sleep(1.0)
                
            except Exception as e:
                print(f"Error polling UI changes: {e}")
                time.sleep(2.0)  # Longer sleep on error
    
    def start_recording(self):
        """Start recording all interactions."""
        self.running = True
        
        # Record initial state
        initial_state = self.capture_ui_state(0, time.time())
        initial_state_file = os.path.join(self.output_dir, "state_0000.json")
        with open(initial_state_file, "w") as f:
            json.dump(initial_state, f, indent=2)
        
        # Start UI polling thread
        ui_thread = threading.Thread(target=self.poll_ui_changes)
        ui_thread.daemon = True
        ui_thread.start()
        
        # Start touch monitoring thread
        touch_thread = threading.Thread(target=self.monitor_touch_events)
        touch_thread.daemon = True
        touch_thread.start()
        
        print("Recording started. Interact with your device.")
        print("Press Ctrl+C to stop recording.")
        
        try:
            # Keep main thread alive until Ctrl+C
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nStopping recording...")
        finally:
            self.running = False
            ui_thread.join(timeout=2.0)
            touch_thread.join(timeout=2.0)
    
    def save_recordings(self):
        """Save recorded interactions to JSON file."""
        if not self.interactions:
            print("Warning: No touch interactions were recorded, but UI state captures should be available.")
        
        # Save interactions log
        interactions_file = os.path.join(self.output_dir, "interactions.json")
        with open(interactions_file, "w") as f:
            json.dump(self.interactions, f, indent=2)
        
        # Create replay data
        replay_data = {
            "device_id": self.device_id,
            "timestamp": self.timestamp,
            "interactions_count": len(self.interactions),
            "states_path": self.output_dir,
            "action_sequence": []
        }
        
        # Process events for replay
        for event in self.interactions:
            if event["event_type"] == "UI_CHANGE":
                replay_data["action_sequence"].append({
                    "action": "ui_change",
                    "timestamp": event["timestamp"],
                    "state_index": event["details"]["state_index"],
                    "package_name": event.get("package_name", ""),
                    "activity_name": event.get("activity_name", "")
                })
        
        # Save replay file
        replay_file = os.path.join(self.output_dir, "replay.json")
        with open(replay_file, "w") as f:
            json.dump(replay_data, f, indent=2)
        
        print(f"\nRecordings saved to directory: {self.output_dir}")
        print(f"  - {len(self.interactions)} interaction events recorded")
        print(f"  - UI states captured as screenshots + JSON")
        print(f"  - Interactions: {interactions_file}")
        print(f"  - Replay data: {replay_file}")

def main():
    print("Android Direct ADB Recorder")
    print("===========================")
    print(f"Device ID: {DEVICE_ID}")
    
    recorder = DirectRecorder(DEVICE_ID)
    
    try:
        # Check device connection
        recorder.check_device_connection()
        
        # Start recording
        recorder.start_recording()
        
        # Save recorded data
        recorder.save_recordings()
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()