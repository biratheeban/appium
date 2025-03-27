########WORKS RELAY
import subprocess
import json
import time
import os
import re

class EmulatorEventReplayer:
    def __init__(self, events_file="emulator_events.json", device_id="emulator-5554"):
        self.events_file = events_file
        self.device_id = device_id
        self.events = []
        self.running = False
    
    def load_events(self):
        """Load events from the JSON file."""
        if not os.path.exists(self.events_file):
            print(f"Error: Events file '{self.events_file}' not found.")
            return False
        
        try:
            with open(self.events_file, 'r') as f:
                self.events = json.load(f)
            if not self.events:
                print("No events found in the file.")
                return False
            print(f"Loaded {len(self.events)} events from {self.events_file}")
            return True
        except Exception as e:
            print(f"Error loading events: {e}")
            return False
    
    def _check_emulator_connected(self):
        """Check if the emulator is connected."""
        try:
            result = subprocess.run(['adb', 'devices'], capture_output=True, text=True, timeout=5)
            return self.device_id in result.stdout
        except Exception as e:
            print(f"Error checking emulator connection: {e}")
            return False
    
    def _get_current_app_info(self):
        """Get current foreground package and activity."""
        try:
            result = subprocess.run(
                f'adb -s {self.device_id} shell dumpsys window | grep -E "mCurrentFocus"',
                shell=True, capture_output=True, text=True, timeout=3
            )
            if result.returncode != 0:
                print(f"Error running dumpsys: {result.stderr}")
                return "unknown", "unknown"
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
            return "unknown", "unknown"
        except Exception as e:
            print(f"Error getting current app info: {e}")
            return "unknown", "unknown"
    
    def _launch_activity(self, package, activity):
        """Launch the specified activity if not already open."""
        current_pkg, current_activity = self._get_current_app_info()
        if current_pkg == package and current_activity == activity:
            print(f"Target activity {package}/{activity} is already open.")
            return True
        
        print(f"Launching {package}/{activity}...")
        try:
            result = subprocess.run(
                f'adb -s {self.device_id} shell am start -n {package}/{activity}',
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                time.sleep(2)  # Wait for activity to launch
                current_pkg, current_activity = self._get_current_app_info()
                if current_pkg == package and current_activity == activity:
                    print(f"Successfully launched {package}/{activity}")
                    return True
                else:
                    print(f"Failed to verify launch of {package}/{activity}. Current: {current_pkg}/{current_activity}")
                    return False
            else:
                print(f"Error launching activity: {result.stderr}")
                return False
        except Exception as e:
            print(f"Error launching activity: {e}")
            return False
    
    def _close_activity(self, package):
        """Close the specified package."""
        print(f"Closing {package}...")
        try:
            result = subprocess.run(
                f'adb -s {self.device_id} shell am force-stop {package}',
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                print(f"Successfully closed {package}")
                return True
            else:
                print(f"Error closing activity: {result.stderr}")
                return False
        except Exception as e:
            print(f"Error closing activity: {e}")
            return False
    
    def _replay_touch_event(self, event):
        """Replay a touch event if coordinates are valid."""
        x = event["coordinates"]["x"]
        y = event["coordinates"]["y"]
        event_type = event["event_type"]
        
        if x is None or y is None:
            print(f"Skipping {event_type} event at timestamp {event['timestamp']} due to null coordinates")
            return
        
        if event_type == "TOUCH_DOWN":
            cmd = f'adb -s {self.device_id} shell input tap {x} {y}'
            print(f"Replaying {event_type} at X:{x}, Y:{y}")
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Error replaying touch event: {result.stderr}")
            time.sleep(0.1)  # Brief delay for tap
        elif event_type == "TOUCH_UP":
            # Handled by tap in TOUCH_DOWN
            pass
        elif event_type == "MOTION":
            print(f"Motion event at X:{x}, Y:{y} (not replayed)")
    
    def _replay_key_event(self, event):
        """Replay a key event."""
        extra_info = event["extra_info"]
        if extra_info.startswith("Key:"):
            key_name = extra_info.split("Key:")[1]
            key_code = self._map_key_name_to_code(key_name)
            if key_code:
                cmd = f'adb -s {self.device_id} shell input keyevent {key_code}'
                event_type = event["event_type"]
                print(f"Replaying {event_type} for key: {key_name} (code: {key_code})")
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                if result.returncode != 0:
                    print(f"Error replaying key event: {result.stderr}")
    
    def _map_key_name_to_code(self, key_name):
        """Map key names to Android key codes."""
        key_map = {
            "ENTER": "66",
            "BACK": "4",
            "HOME": "3",
            "MENU": "82",
            "VOLUME_UP": "24",
            "VOLUME_DOWN": "25",
        }
        return key_map.get(key_name.upper(), None)
    
    def replay_events(self):
        """Replay all loaded events with improved error handling."""
        if not self._check_emulator_connected():
            print(f"Emulator {self.device_id} not found. Please start the emulator.")
            return
        
        if not self.load_events():
            return
        
        if not self.events:
            print("No events to replay.")
            return
        
        package = self.events[0]["package"]
        activity = self.events[0]["activity"]
        
        if not self._launch_activity(package, activity):
            print("Failed to launch activity. Aborting replay.")
            return
        
        self.running = True
        print(f"\nReplaying {len(self.events)} events...")
        
        # Use a simple delay between events instead of timestamp parsing
        event_count = 0
        for event in self.events:
            if not self.running:
                print("Replay interrupted.")
                break
            
            try:
                if event["event_type"] in ["TOUCH_DOWN", "TOUCH_UP", "MOTION"]:
                    self._replay_touch_event(event)
                elif event["event_type"] in ["KEY_DOWN", "KEY_UP"]:
                    self._replay_key_event(event)
                event_count += 1
                print(f"Processed event {event_count}/{len(self.events)}")
                time.sleep(0.05)  # Small delay between events
            except Exception as e:
                print(f"Error replaying event at timestamp {event['timestamp']}: {e}")
                continue
        
        print("\nReplay completed.")
        
        self._close_activity(package)
    
    def _parse_timestamp(self, timestamp_str):
        """Parse timestamp to seconds since start (kept for reference, not used)."""
        try:
            h, m, s = map(float, timestamp_str.split(':'))
            return h * 3600 + m * 60 + s
        except Exception:
            return None
    
    def stop(self):
        """Stop the replay."""
        self.running = False

if __name__ == "__main__":
    replayer = EmulatorEventReplayer()
    replayer.replay_events()