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

# Insert button event, wc, bet, assume, and lc into MySQL database
def insert_button_event(connection, game_result, wc, bet, assume, lc):
    try:
        cursor = connection.cursor()
        query = "INSERT INTO results (game_result, wc, bet, assume, lc) VALUES (%s, %s, %s, %s, %s)"
        cursor.execute(query, (game_result, wc, bet, assume, lc))
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
def place_bet(bet_target, click_times):
    unselect_bet()  # Ensure previous bet is unselected before placing a new one
    target_region = button_regions[bet_target]
    
    # Click the betting button the required number of times
    for _ in range(click_times):
        pyautogui.moveTo(target_region["left"] + target_region["width"] / 2,
                         target_region["top"] + target_region["height"] / 2)
        pyautogui.click()  # Place the bet with one click
        print(f"Placed a bet on {bet_target}, clicks {click_times}")

    # Move cursor away from buttons to avoid multiple clicks
    pyautogui.moveTo(result_unselect_position["x"], result_unselect_position["y"])

# Function to unselect the bet after the result is displayed
def unselect_after_result():
    pyautogui.moveTo(result_unselect_position["x"], result_unselect_position["y"])
    pyautogui.click()  # Click once to unselect any bet

# Update assumption based on previous results
def update_assumption(previous_results):
    if len(previous_results) == 0:
        return None  # No results yet

    first_result = previous_results[0]
    
    # Calculate the current block: whether we are in the first block of 6 or the second, etc.
    rounds_since_first_result = len(previous_results)
    
    if rounds_since_first_result <= 6:
        current_assumption = first_result
    elif 7 <= rounds_since_first_result <= 12:
        current_assumption = "banker" if first_result == "player" else "player"
    else:
        block = (rounds_since_first_result - 1) // 6
        if block % 2 == 0:
            current_assumption = first_result
        else:
            current_assumption = "banker" if first_result == "player" else "player"

    print(f"Current Assumption: {current_assumption}")
    return current_assumption

# Main function to handle detection, betting, and result-checking logic
def run_betting_script():
    connection = create_connection()
    if connection is None:
        return

    with mss.mss() as sct:
        prev_button_colors = {button: None for button in button_regions}
        last_change_time = {button: 0 for button in button_regions}
        color_change_cooldown = 4

        previous_results = []            # Store results history (only Player/Banker)
        previous_assumption = None       # Initialize with no assumption
        previous_game_result = None     # Track the previous game result (player or banker)
        current_lc = 0                  # Line count starts at L1
        initial_bet = 5                 # Bet for all rounds after the first round
        bet = 0                          # The first round bet is 0
        wc_zero_count = 0               # To track consecutive wc=0 outcomes
        waiting_for_result = False      # Controls when to detect results
        bets_open_detected = False      # Flag to ensure we detect BETS OPEN only once per round
        round_complete = True           # Ensure a full round completes before restarting
        round_count = 0                 # Track the current round

        while True:
            if not waiting_for_result and round_complete and not bets_open_detected:
                if detect_bets_open_text(sct):
                    if previous_assumption is not None:
                        # Reset bet for second round to initial_bet
                        if round_count == 2:
                            bet = initial_bet
                            place_bet(previous_assumption, 1)  # Place bet once

                        # Adjust the bet based on the wc_zero_count
                        elif wc_zero_count == 0:
                            bet = initial_bet
                            place_bet(previous_assumption, 1)  # Place bet once
                        elif wc_zero_count == 1:
                            bet = initial_bet * 2
                            place_bet(previous_assumption, 2)  # Place bet twice
                        elif wc_zero_count == 2:
                            bet = initial_bet * 4
                            place_bet(previous_assumption, 4)  # Place bet four times
                        elif wc_zero_count == 3:
                            bet = initial_bet
                            place_bet(previous_assumption, 1)  # Place bet once
                            wc_zero_count = 0  # Reset after 3 consecutive zeros

                    waiting_for_result = True
                    bets_open_detected = True
                    round_complete = False
                    print(f" Round {round_count +1} Waiting for the game result...  ,Bet: {bet} ")

                    prev_button_colors = {button: None for button in button_regions}
                    time.sleep(10)

            if waiting_for_result:
                for button_name, button_region in button_regions.items():
                    if button_name == "tie":
                        continue

                    current_color = capture_button_color(button_region, sct)

                    if prev_button_colors[button_name] is not None:
                        color_diff = np.linalg.norm(current_color - prev_button_colors[button_name])

                        if color_diff > 15 and (time.time() - last_change_time[button_name] > color_change_cooldown):
                            # Determine the wc value
                            wc = 1 if button_name == previous_assumption else 0

                            # Determine the lc value
                            if previous_game_result == button_name:
                                lc = current_lc  # Same result, keep lc the same
                            else:
                                current_lc += 1  # Different result, increment lc
                                lc = current_lc

                            # Insert result, wc, bet, assumption, and lc into the database
                            insert_button_event(connection, button_name, wc, bet, previous_assumption, f"L{lc}")
                            print(f"{button_name} WON - wc: {wc}, Bet: {bet}, Assumption: {previous_assumption}, lc: L{lc}")

                            # Update wc_zero_count based on wc
                            if wc == 0:
                                wc_zero_count += 1
                            else:
                                wc_zero_count = 0  # Reset count when wc=1

                            # Only consider Player/Banker results for pattern detection
                            if button_name != "tie":
                                previous_results.append(button_name)

                            # Update assumption
                            previous_assumption = update_assumption(previous_results)

                            # Update the previous game result for lc comparison
                            previous_game_result = button_name

                            # Reset round states
                            waiting_for_result = False
                            bets_open_detected = False
                            round_complete = True
                            last_change_time[button_name] = time.time()

                            # Increment round count
                            round_count += 1

                            print("--------------------------------------NEXT ROUND-----------------------------------------")

                            # Automatically unselect the bet after result
                            unselect_after_result()

                    prev_button_colors[button_name] = current_color

            time.sleep(0.1)

    connection.close()

# Run the betting script
run_betting_script()
