import time
import json
import threading
import traceback
from appium import webdriver
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions.pointer_actions import PointerActions
from selenium.webdriver.common.actions.key_actions import KeyActions
from appium.options.android import UiAutomator2Options
from selenium.common.exceptions import InvalidSessionIdException, WebDriverException


class AndroidInteractionRecorder:
    def __init__(self):
        self.options = UiAutomator2Options()
        self.options.platform_name = "Android"
        self.options.automation_name = "UiAutomator2"
        self.options.device_name = "emulator-5554"
        self.options.new_command_timeout = 600
        self.options.no_reset = True
        
        self.driver = None
        self.interactions = []
        self.recording = False
        self.monitor_thread = None
        self.session_active = False
    
    def get_current_activity(self):
        """Get the current foreground app package and activity"""
        if not self.session_active:
            return None, None
            
        try:
            return self.driver.current_package, self.driver.current_activity
        except (InvalidSessionIdException, WebDriverException):
            self.session_active = False
            return None, None
        except Exception as e:
            print(f"Error getting current activity: {e}")
            return None, None
    
    def establish_session(self):
        """Establish a new Appium session"""
        try:
            print("Connecting to Appium server...")
            self.driver = webdriver.Remote("http://localhost:4723", options=self.options)
            print("Connected successfully")
            self.session_active = True
            return True
        except Exception as e:
            print(f"Failed to connect to Appium: {e}")
            self.session_active = False
            return False
    
    def safe_quit_driver(self):
        """Safely quit the driver without raising exceptions"""
        if self.driver:
            try:
                self.driver.quit()
            except (InvalidSessionIdException, WebDriverException):
                print("Driver session was already terminated")
            except Exception as e:
                print(f"Error while quitting driver: {e}")
            finally:
                self.driver = None
                self.session_active = False
    
    def start_recording(self):
        """Start recording user interactions"""
        if not self.establish_session():
            print("Failed to start recording: could not establish Appium session")
            return
            
        self.recording = True
        print("Recording started. Interact with the app...")
        
        self.monitor_thread = threading.Thread(target=self.monitor_interactions, daemon=True)
        self.monitor_thread.start()
        
        try:
            while self.recording:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Keyboard interrupt received")
        finally:
            self.stop_recording()
    
    def stop_recording(self):
        """Stop recording interactions"""
        print("Stopping recording...")
        self.recording = False
        self.safe_quit_driver()
        print("Recording stopped")
    
    def save_to_json(self, filename="interactions.json"):
        """Save recorded interactions to a JSON file"""
        if not self.interactions:
            print("No interactions to save")
            return
            
        with open(filename, "w") as f:
            json.dump(self.interactions, f, indent=4)
        print(f"Interactions saved to {filename}")
    
    def monitor_interactions(self):
        """Monitor and record user interactions"""
        last_activity = None
        reconnect_attempts = 0
        max_reconnect_attempts = 3
        
        try:
            while self.recording:
                # Check if session is still active
                if not self.session_active:
                    reconnect_attempts += 1
                    print(f"Session inactive. Attempting to reconnect ({reconnect_attempts}/{max_reconnect_attempts})...")
                    
                    if reconnect_attempts > max_reconnect_attempts:
                        print("Max reconnection attempts reached. Stopping recording.")
                        self.recording = False
                        break
                    
                    if not self.establish_session():
                        print("Reconnection failed. Waiting before next attempt...")
                        time.sleep(5)
                        continue
                    else:
                        reconnect_attempts = 0
                
                package, activity = self.get_current_activity()
                
                if package and activity and activity != last_activity:
                    self.interactions.append({
                        "type": "app_change",
                        "timestamp": time.time(),
                        "package": package,
                        "activity": activity
                    })
                    print(f"App changed: {package}/{activity}")
                    last_activity = activity
                
                time.sleep(1)
        except Exception as e:
            print(f"Error during monitoring: {e}")
            traceback.print_exc()
            self.recording = False


if __name__ == "__main__":
    recorder = AndroidInteractionRecorder()
    try:
        recorder.start_recording()
    except Exception as e:
        print(f"Unexpected error: {e}")
        traceback.print_exc()
    finally:
        recorder.stop_recording()
        recorder.save_to_json()