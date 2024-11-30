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
    "player": {"top": 550, "left": 205, "width": 100, "height": 75},
    "banker": {"top": 550, "left": 415, "width": 100, "height": 75},
}

# Define the region for detecting numeric round text (1-12)
bets_open_region = {"top": 295, "left": 475, "width": 50, "height": 50}

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
def insert_button_event(connection, game_result, wc):
    try:
        cursor = connection.cursor()
        query = "INSERT INTO results (game_result, wc) VALUES (%s, %s)"
        cursor.execute(query, (game_result, wc))
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

# Detect numeric round number (1-12) in the specified region
def detect_bets_open_text(sct):
    screenshot = sct.grab(bets_open_region)
    img = np.array(screenshot)
    processed_img = preprocess_image(img)
    text = pytesseract.image_to_string(processed_img, config='--psm 8')
    detected_text = text.strip()
    print("Detected text:", detected_text)
    if detected_text.isdigit() and 1 <= int(detected_text) <= 12:
        return int(detected_text)
    return None

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
        previous_game_result = None  # Initialize with None, as we'll detect the first result
        waiting_for_result = False       # Controls when to detect results
        bets_open_detected = False       # Flag to ensure we detect BETS OPEN only once per round
        round_complete = True            # Ensure a full round completes before restarting
        assumption = None  # The current assumption (either 'player' or 'banker')
        round_counter = 0  # To keep track of rounds for switching assumptions

        while True:
            # Check for numeric round number (1-12) if not waiting for result and previous round completed
            if not waiting_for_result and round_complete and not bets_open_detected:
                detected_value = detect_bets_open_text(sct)
                if detected_value is not None:
                    print(f"Detected round number: {detected_value}")
                    if previous_game_result is None:
                        # Wait for the first result
                        print("Waiting for the first result...")
                        waiting_for_result = True
                        bets_open_detected = True   # Set flag so we don't repeatedly detect round number
                        round_complete = False      # Mark round as in progress
                    else:
                        # Place bet based on the previous assumption
                        place_bet(assumption)
                        waiting_for_result = True   # Start waiting for the game result
                        bets_open_detected = True   # Set flag so we don't repeatedly detect round number
                        round_complete = False      # Mark round as in progress
                        print(f"Placed a bet on {assumption} based on previous result")

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
                            # Log result to the database and update previous game result
                            wc = 1 if button_name == assumption else 0
                            insert_button_event(connection, button_name, wc)
                            print(f"{button_name} WON (wc: {wc})")

                            # Update previous game result and reset waiting status
                            previous_game_result = button_name
                            if round_counter >= 6:
                                # Switch assumption after 6 rounds
                                assumption = "banker" if assumption == "player" else "player"
                                round_counter = 0  # Reset counter after switching assumption
                            else:
                                # Continue with the same assumption
                                assumption = previous_game_result
                                round_counter += 1
                            
                            waiting_for_result = False
                            bets_open_detected = False  # Reset the flag for next round
                            round_complete = True       # Mark the round as complete
                            last_change_time[button_name] = time.time()
                            print("--------------------------------------NEXT ROUND-----------------------------------------")

                            # Automatically unselect the bet after result
                            unselect_after_result()

                    prev_button_colors[button_name] = current_color

            time.sleep(0.1)
    connection.close()

# Run the betting script
run_betting_script()
