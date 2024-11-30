import numpy as np
import mss
import pyautogui
import time  # Import time for sleep functionality

# Define regions for Player, Banker, Tie buttons
button_regions = {
    "player": {"top": 550, "left": 205, "width": 100, "height": 75},
    "banker": {"top": 550, "left": 415, "width": 100, "height": 75},
    # "tie": {"top": 630, "left": 300, "width": 100, "height": 50}
}

# Define the region for detecting "BETS OPEN" text
bets_open_region = {"top": 295, "left": 475, "width": 50, "height": 50}

# Function to check if the mouse is within a given region
def is_mouse_in_region(region):
    mouse_x, mouse_y = pyautogui.position()
    in_x = region["left"] <= mouse_x <= region["left"] + region["width"]
    in_y = region["top"] <= mouse_y <= region["top"] + region["height"]
    return in_x and in_y

# Function to display hover effect for all regions
def display_hover_feedback():
    with mss.mss() as sct:
        while True:
            hover_detected = False  # Track if any region is hovered

            # Check for hover in button regions
            for button_name, region in button_regions.items():
                if is_mouse_in_region(region):
                    print(f"Mouse hovered over: {button_name.upper()} (Region: {region})")
                    hover_detected = True
                    break  # Avoid checking other regions once a match is found

            # Check for hover in "BETS OPEN" region if no button region is hovered
            if not hover_detected:
                if is_mouse_in_region(bets_open_region):
                    print(f"Mouse hovered over: BETS OPEN region (Coordinates: {bets_open_region})")
                    hover_detected = True

            # If no regions are hovered, provide feedback
            if not hover_detected:
                print("Mouse is not over any defined region", end="\r")

            # Delay to prevent flooding the console
            time.sleep(0.1)

# Run the hover detection
display_hover_feedback()