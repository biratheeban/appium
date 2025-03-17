import time
import json
import sys
from appium import webdriver
from appium.webdriver.common.appiumby import AppiumBy
from appium.options.android import UiAutomator2Options
from selenium.common.exceptions import WebDriverException


class AndroidInteractionReplayer:
    def __init__(self, json_file):
        self.options = UiAutomator2Options()
        self.options.platform_name = "Android"
        self.options.automation_name = "UiAutomator2"
        self.options.device_name = "emulator-5554"
        self.options.new_command_timeout = 600
        self.options.no_reset = True
        
        self.options.app_package = "io.appium.settings"
        self.options.app_activity = ".Settings"
        
        self.driver = None
        self.interactions = []
        self.json_file = json_file
        
    def load_interactions(self):
        """Load recorded interactions from JSON file"""
        try:
            with open(self.json_file, 'r') as f:
                self.interactions = json.load(f)
            print(f"Loaded {len(self.interactions)} interactions from {self.json_file}")
            return True
        except Exception as e:
            print(f"Failed to load interactions: {e}")
            return False
    
    def establish_session(self):
        """Establish a new Appium session"""
        try:
            print("Connecting to Appium server...")
            self.driver = webdriver.Remote("http://localhost:4723", options=self.options)
            print("Connected successfully")
            return True
        except Exception as e:
            print(f"Failed to connect to Appium: {e}")
            return False
    
    def safe_quit_driver(self):
        """Safely quit the driver without raising exceptions"""
        if self.driver:
            try:
                self.driver.quit()
            except WebDriverException:
                print("Driver session was already terminated")
            except Exception as e:
                print(f"Error while quitting driver: {e}")
            finally:
                self.driver = None
    
    def navigate_to_activity(self, package, activity):
        """Navigate to a specific activity"""
        try:
            full_activity = f"{package}/{activity}"
            print(f"Navigating to: {full_activity}")
            
            # Using Android's Intent mechanism through Appium
            print("Using Android Intent to start activity")
            activity_name = activity
            if activity.startswith("."):
                activity_name = package + activity
                
            # Method 1: Using activateApp
            print("Trying activateApp...")
            self.driver.activate_app(package)
            time.sleep(2)
            
            # Check if we launched the correct app
            current_package = self.driver.current_package
            current_activity = self.driver.current_activity
            print(f"Current focus: {current_package}/{current_activity}")
            
            # If we're not in the right package or activity, use alternative methods
            if current_package != package or not (current_activity == activity or activity.endswith(current_activity)):
                # Method 2: Using direct intent
                print("Trying direct intent...")
                intent = {
                    'action': 'android.intent.action.MAIN',
                    'category': 'android.intent.category.LAUNCHER',
                    'flags': 0x10200000,
                    'package': package,
                    'activity': activity_name
                }
                self.driver.execute_script('mobile: startActivity', intent)
                time.sleep(2)
            
            # Verify we reached the correct app
            current_package = self.driver.current_package
            current_activity = self.driver.current_activity
            print(f"Final activity: {current_package}/{current_activity}")
            
            if current_package == package:
                print("Navigation successful")
                return True
            else:
                print(f"Package mismatch - Expected: {package}, Got: {current_package}")
                return False
            
        except Exception as e:
            print(f"Failed to navigate to activity: {e}")
            return False
    
    def replay(self):
        """Replay the recorded interactions"""
        if not self.load_interactions():
            return
        
        if not self.establish_session():
            return
        
        try:
            # Filter only app_change interactions
            app_changes = [i for i in self.interactions if i["type"] == "app_change"]
            
            if not app_changes:
                print("No app navigation events found to replay")
                return
            
            print(f"Found {len(app_changes)} app navigation events to replay")
            
            for i, interaction in enumerate(app_changes):
                print(f"\nReplaying interaction {i+1}/{len(app_changes)}")
                
                if interaction["type"] == "app_change":
                    package = interaction["package"]
                    activity = interaction["activity"]
                    
                    # If this is not the first interaction, calculate wait time from timestamps
                    if i > 0:
                        wait_time = interaction["timestamp"] - app_changes[i-1]["timestamp"]
                        print(f"Original wait time was {wait_time:.2f} seconds")
                        
                        # Cap wait time to reasonable limits (1-10 seconds)
                        wait_time = max(1, min(wait_time, 10))
                        print(f"Waiting {wait_time:.2f} seconds before next action")
                        time.sleep(wait_time)
                    
                    success = self.navigate_to_activity(package, activity)
                    if not success:
                        print("Warning: Navigation may have failed")
            
            print("\nReplay completed!")
            
        except Exception as e:
            print(f"Error during replay: {e}")
        finally:
            self.safe_quit_driver()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        json_file = sys.argv[1]
    else:
        json_file = "interactions.json"
    
    replayer = AndroidInteractionReplayer(json_file)
    replayer.replay()