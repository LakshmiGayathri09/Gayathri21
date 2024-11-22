import time
import numpy as np
import mss
import pyautogui
import cv2
import mysql.connector
from mysql.connector import Error
import pytesseract

pyautogui.FAILSAFE = False

# Define regions for each button (player, banker, tie)
button_regions = {
    "player": {"top": 630, "left": 180, "width": 100, "height": 50},
    "banker": {"top": 630, "left": 420, "width": 100, "height": 50},
    "tie": {"top": 630, "left": 300, "width": 100, "height": 50}
}

# Region for detecting the "BETS OPEN" text
bets_open_region = {"top": 330, "left": 245, "width": 200, "height": 30}

# Set path to Tesseract executable
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# Define the coordinates for an empty area on the website to unselect a bet
unselect_coordinates = {"x": 252, "y": 9827}  # Replace with actual coordinates for unselecting
result_unselect_position = {"x": 50, "y": 960}  # Position to move to and click after result

def create_connection():
    try:
        connection = mysql.connector.connect(
            host="localhost",
            user="root",
            password="root",
            database="game_results"
        )
        if connection.is_connected():
            print("Connected to MySQL database")
        return connection
    except Error as e:
        print("Error connecting to MySQL", e)
        return None

# Insert button event into MySQL database
def insert_button_event(connection, game_result):
    try:
        cursor = connection.cursor()
        query = "INSERT INTO results (game_result) VALUES (%s)"
        cursor.execute(query, (game_result,))
        connection.commit()
    except Error as e:
        print("Error inserting into MySQL table", e)

def capture_button_color(region, sct):
    screenshot = sct.grab(region)
    button_frame = np.array(screenshot)
    avg_color = np.mean(button_frame, axis=(0, 1))
    return avg_color

def preprocess_image(img):
    gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    contrast_img = cv2.convertScaleAbs(gray_img, alpha=1.5, beta=0)
    denoised_img = cv2.GaussianBlur(gray_img, (5, 5), 0)
    thresh_img = cv2.adaptiveThreshold(gray_img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
    return thresh_img

# Detect "BETS OPEN" text in the specified region
def detect_bets_open_text(sct):
    screenshot = sct.grab(bets_open_region)
    img = np.array(screenshot)
    processed_img = preprocess_image(img)
    cv2.imwrite('debug_bets_open_region.png', processed_img)
    text = pytesseract.image_to_string(processed_img, config='--psm 8')
    print("Detected text:", text.strip())
    return "BETS OPEN" in text.upper()

# Function to click on an empty area to unselect any current bet
def unselect_bet():
    pyautogui.moveTo(unselect_coordinates["x"], unselect_coordinates["y"])
    pyautogui.click()  # Click on the empty area

# Function to place a bet on player or banker (only click once)
def place_bet(bet_target):
    unselect_bet()  # Ensure previous bet is unselected before placing a new one
    target_region = button_regions[bet_target]
    pyautogui.moveTo(target_region["left"] + target_region["width"] / 2,
                     target_region["top"] + target_region["height"] / 2)
    pyautogui.click()  # Place the bet with one click
    print(f"Placed a bet on {bet_target}")

    # Move cursor away from buttons to avoid multiple clicks
    pyautogui.moveTo(result_unselect_position["x"], result_unselect_position["y"])

# Function to unselect the bet after the result is displayed
def unselect_after_result():
    pyautogui.moveTo(result_unselect_position["x"], result_unselect_position["y"])
    pyautogui.click()  # Click once to unselect any bet

# Main function to handle detection, betting, and result-checking logic

def run_betting_script():
    connection = create_connection()
    if connection is None:
        return

    with mss.mss() as sct:
        prev_button_colors = {button: None for button in button_regions}
        last_change_time = {button: 0 for button in button_regions}
        color_change_cooldown = 4
        previous_results = []  # To store the sequence of valid results (excluding ties)
        last_assumed_result = None  # Current betting assumption
        waiting_for_result = False  # Controls when to detect results
        bets_open_detected = False  # Flag to ensure we detect BETS OPEN only once per round
        round_complete = True  # Ensure a full round completes before restarting

        while True:
            # Check for "BETS OPEN" text if not waiting for result and previous round completed
            if not waiting_for_result and round_complete and not bets_open_detected:
                if detect_bets_open_text(sct):
                    # Place bet based on the last assumption, if available
                    if last_assumed_result is not None:
                        place_bet(last_assumed_result)
                    else:
                        print("No previous assumption. Skipping the first round.")

                    waiting_for_result = True  # Start waiting for the game result
                    bets_open_detected = True  # Set flag so we don't repeatedly detect "BETS OPEN"
                    round_complete = False  # Mark round as in progress
                    print("Waiting for the game result...")

                    # Clear previous button colors to ensure fresh detection
                    prev_button_colors = {button: None for button in button_regions}

                    # Fixed delay to allow the game result to appear (adjust as needed)
                    time.sleep(10)

            # Detect color change to confirm win/loss only when waiting for result
            if waiting_for_result:
                for button_name, button_region in button_regions.items():
                    current_color = capture_button_color(button_region, sct)

                    # Check for significant color change as a win/loss signal
                    if prev_button_colors[button_name] is not None:
                        color_diff = np.linalg.norm(current_color - prev_button_colors[button_name])

                        if color_diff > 15 and (time.time() - last_change_time[button_name] > color_change_cooldown):
                            # Log result to the database
                            insert_button_event(connection, button_name)
                            print(f"{button_name} WON")

                            # Update result history and assumption logic
                            if button_name != "tie":
                                previous_results.append(button_name)

                            # Update betting assumption based on the result history
                            last_assumed_result = update_assumption(previous_results, button_name)

                            waiting_for_result = False
                            bets_open_detected = False  # Reset the flag for the next round
                            round_complete = True  # Mark the round as complete
                            last_change_time[button_name] = time.time()
                            print("--------------------------------------NEXT ROUND-----------------------------------------")

                            # Automatically unselect the bet after result
                            unselect_after_result()

                    prev_button_colors[button_name] = current_color

            time.sleep(0.1)
    connection.close()


def update_assumption(results, current_result):
    """
    Updates the betting assumption based on the given results.
    """
    if len(results) == 0:
        # First result, no assumption yet
        print("First result detected. No assumption made.")
        return None

    if len(results) == 1:
        # Only one result available, assume the same
        print("One result available. Assuming:", results[-1])
        return results[-1]

    if len(results) == 2:
        # Two results, handle same and opposite patterns
        if results[-1] == results[-2]:
            print("Two consecutive same results. Assuming:", results[-1])
            return results[-1]
        else:
            print("Two alternating results. Assuming:", "player" if results[-1] == "banker" else "banker")
            return "player" if results[-1] == "banker" else "banker"

    if current_result == "tie":
        # Ignore ties for assumption, retain the previous assumption
        print("Result is tie. Keeping the previous assumption.")
        return results[-1]

    # Check for continuous same pattern
    if results[-1] == results[-2] and results[-2] == results[-3]:
        print("Detected 3+ consecutive same results. Assuming:", results[-1])
        return results[-1]

    # Check for alternating pattern
    if len(results) >= 3:
        if results[-3:] == ["player", "banker", "player"] or results[-3:] == ["banker", "player", "banker"]:
            print("Detected alternating pattern. Assuming:", "banker" if results[-1] == "player" else "player")
            return "banker" if results[-1] == "player" else "player"

    # Check for 2 same + 1 different
    if results[-1] != results[-2] and results[-2] == results[-3]:
        print("Detected 2 same + 1 different. Assuming:", results[-1])
        return results[-1]

    # Default to the last result
    elif results[-2] == results[-1]:
        print("Two previous results are same. Assuming last result:", previous_assumption)
    else:
        previous_assumption = "player" if results[1] == "banker" else "banker"
        print("Two different results. Assuming:", previous_assumption)

# Add the unselect_after_result function to click at the unselect position after a result is detected
def unselect_after_result():
    pyautogui.moveTo(50, 950)
    pyautogui.click()  # Click to unselect the bet

# Run the betting script
run_betting_script()

update_assumption()
