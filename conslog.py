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

# Insert button event and wc value into MySQL database with lc (line count)
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

def place_bet(bet_target, bet, initial_bet):
    unselect_bet()  # Ensure previous bet is unselected before placing a new one
    target_region = button_regions[bet_target]

    # Calculate how many times to click based on the bet amount
    click_count = bet // initial_bet

    for _ in range(click_count):
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


# Betting logic
def betting_logic(wc_sequence, initial_bet):
    bet_history = []  # To keep track of bets

    consecutive_zeroes = 0  # To track consecutive zeros
    for i, wc in enumerate(wc_sequence):
        if i == 0:
            # For the first game, we don't bet, so the bet is None
            bet = initial_bet
        elif wc == 1:
            # If wc is 1, bet is always 1
            bet = initial_bet
            consecutive_zeroes = 0
        else:  # wc == 0
            # If wc is 0, count consecutive zeros and adjust bet accordingly
            consecutive_zeroes += 1

            if consecutive_zeroes == 1:
                bet = initial_bet * 2  # Bet is 2 after the first zero
            elif consecutive_zeroes == 2:
                bet = initial_bet * 4  # Bet is 4 after the second consecutive zero
            elif consecutive_zeroes == 3:
                bet = initial_bet * 1  # Bet is 1 after the third consecutive zero
                consecutive_zeroes = 0  # Reset after three zeros

        bet_history.append(bet)

    return bet_history


# Main function to handle detection, betting, and result-checking logic
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

    print(f"Round {rounds_since_first_result}: Current Assumption: {current_assumption}")
    return current_assumption

# The main betting script
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
        waiting_for_result = False       # Controls when to detect results
        bets_open_detected = False       # Flag to ensure we detect BETS OPEN only once per round
        round_complete = True            # Ensure a full round completes before restarting

        round_number = 0                 # Track the round number to control bet logic
        wc_sequence = []                 # Track the wc sequence to pass into betting_logic

        bet = 1  # Set the initial bet to 1
        initial_bet = 5  # Set the initial bet amount to 5

        while True:
            if not waiting_for_result and round_complete and not bets_open_detected:
                if detect_bets_open_text(sct):
                    if previous_assumption is not None:
                        # Determine bet amount for the current round
                        bet_history = betting_logic(wc_sequence, initial_bet)
                        bet_amount = bet_history[-1]  # Take the last bet in the sequence

                        if bet_amount > 0:
                            print(f"Round {round_number + 1}: Waiting for the game result... Bet: {bet_amount}")

                        # Place bet based on the previous assumption
                        place_bet(previous_assumption, bet_amount, initial_bet)
                    waiting_for_result = True
                    bets_open_detected = True
                    round_complete = False
                    print("Waiting for the game result...")

                    round_number += 1  # Increment round number for the next cycle
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
                            insert_button_event(connection, button_name, wc, bet_amount, previous_assumption, f"L{lc}")
                            print(f"{button_name} WON - wc: {wc}, Bet: {bet_amount}, Assumption: {previous_assumption}, lc: L{lc}")

                            # Update the previous game result for lc comparison
                            previous_game_result = button_name

                            # Only consider Player/Banker results for pattern detection
                            if button_name != "tie":
                                previous_results.append(button_name)
                                wc_sequence.append(wc)  # Append the wc value to the sequence

                            # Update assumption
                            previous_assumption = update_assumption(previous_results)

                            # Reset round states
                            waiting_for_result = False
                            bets_open_detected = False
                            round_complete = True
                            last_change_time[button_name] = time.time()
                            print("--------------------------------------NEXT ROUND-----------------------------------------")

                            # Automatically unselect the bet after result
                            unselect_after_result()

                    prev_button_colors[button_name] = current_color

            time.sleep(0.1)

    connection.close()

# Run the betting script
run_betting_script()

