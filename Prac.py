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
bets_open_region = {"top": 335, "left": 245, "width": 200, "height": 30}

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
# Main function to handle detection, betting, and result-checking logic
def run_betting_script():
    connection = create_connection()
    if connection is None:
        return

    with mss.mss() as sct:
        prev_button_colors = {button: None for button in button_regions}
        last_change_time = {button: 0 for button in button_regions}
        color_change_cooldown = 4
        previous_results = []  # Track the last three results
        waiting_for_result = False       # Controls when to detect results
        bets_open_detected = False       # Flag to ensure we detect BETS OPEN only once per round
        round_complete = True            # Ensure a full round completes before restarting

        while True:
            # Check for "BETS OPEN" text if not waiting for result and previous round completed
            if not waiting_for_result and round_complete and not bets_open_detected:
                if detect_bets_open_text(sct):
                    # Determine the next bet based on the previous results
                    next_bet = None
                    if len(previous_results) >= 3:
                        # Case 1: All three results are the same (e.g., player, player, player)
                        if previous_results[-1] == previous_results[-2] == previous_results[-3]:
                            next_bet = previous_results[-1]  # Repeat the same result

                        # Case 2: The last three results alternate (e.g., banker, player, banker)
                        elif (previous_results[-1] != previous_results[-2] and
                              previous_results[-2] != previous_results[-3] and
                              previous_results[-1] == previous_results[-3]):
                            next_bet = 'player' if previous_results[-1] == 'banker' else 'banker'  # Opposite of last

                        # Case 3: The first two of the last three are the same, followed by a different result
                        elif previous_results[-1] != previous_results[-2] and previous_results[-2] == previous_results[-3]:
                            next_bet = previous_results[-1]  # Bet on the most recent different result

                    elif len(previous_results) >= 2:
                        # If the last two results are the same, repeat the last result
                        if previous_results[-1] == previous_results[-2]:
                            next_bet = previous_results[-1]

                    # Default to a 'player' bet if no specific pattern is found
                    if next_bet is None:
                        next_bet = 'player'

                    place_bet(next_bet)

                    waiting_for_result = True   # Start waiting for the game result
                    bets_open_detected = True   # Set flag so we don't repeatedly detect "BETS OPEN"
                    round_complete = False      # Mark round as in progress
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
                            # Log result to the database and update previous game result
                            insert_button_event(connection, button_name)
                            print(f"{button_name} WON")

                            # Add the result to the previous_results list
                            if len(previous_results) >= 3:
                                previous_results.pop(0)  # Keep only the last three results
                            previous_results.append(button_name)

                            # Reset for next round
                            waiting_for_result = False
                            round_complete = True
                            bets_open_detected = False
                    prev_button_colors[button_name] = current_color

            time.sleep(0.1)
    connection.close()

# Run the betting script
run_betting_script()
