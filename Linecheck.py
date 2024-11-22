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

    # Variables to store the results and pattern info
    game_results = []  # List to track each line of results
    current_line = []  # List to track results for the current line (e.g., player, player)
    last_assumed_result = None  # Stores the assumed result for the next round
    previous_results = []  # Keep track of the last few results to detect the pattern
    line_number = 1  # Track line numbers for printing results

    with mss.mss() as sct:
        prev_button_colors = {button: None for button in button_regions}
        last_change_time = {button: 0 for button in button_regions}
        color_change_cooldown = 4
        waiting_for_result = False
        bets_open_detected = False
        round_complete = True

        while True:
            if not waiting_for_result and round_complete and not bets_open_detected:
                if detect_bets_open_text(sct):
                    if last_assumed_result is None:
                        print("First round detected, waiting for result.")
                    else:
                        place_bet(last_assumed_result)
                    
                    waiting_for_result = True
                    bets_open_detected = True
                    round_complete = False
                    print("Waiting for the game result...")

                    prev_button_colors = {button: None for button in button_regions}
                    time.sleep(10)

            if waiting_for_result:
                for button_name, button_region in button_regions.items():
                    current_color = capture_button_color(button_region, sct)

                    if prev_button_colors[button_name] is not None:
                        color_diff = np.linalg.norm(current_color - prev_button_colors[button_name])

                        if color_diff > 15 and (time.time() - last_change_time[button_name] > color_change_cooldown):
                            insert_button_event(connection, button_name)
                            print(f"{button_name} WON")

                            if last_assumed_result is None:
                                last_assumed_result = button_name
                                print(f"First result detected: {button_name}")
                            else:
                                if button_name == "tie":
                                    print("Result is a tie, assuming the previous round's assumption.")
                                else:
                                    if len(previous_results) <= 2:
                                        # Handle cases where there are 2 or fewer previous results
                                        if len(previous_results) > 1 and previous_results[-2] == previous_results[-1]:
                                            # Same pattern for 2 results
                                            if button_name == previous_results[-1]:
                                                current_line.append(button_name)
                                            else:
                                                game_results.append(current_line)
                                                current_line = [button_name]
                                                line_number += 1
                                        elif len(previous_results) > 1:
                                        # Opposite pattern for 2 results
                                            if button_name != previous_results[-1]:
                                                game_results.append(current_line)
                                                current_line = [button_name]
                                                line_number += 1
                                            else:
                                                current_line.append(button_name)

                                    else:
                                    # Handle cases where there are 3 or more previous results
                                        if all(x == previous_results[-1] for x in previous_results[-2:]):
                                        # Same pattern for 3 results
                                            last_assumed_result = previous_results[-1]
                                            print("Detected same pattern for 3 results, assuming the same:", last_assumed_result)
                                            if button_name == last_assumed_result:
                                                current_line.append(button_name)
                                            else:
                                                game_results.append(current_line)
                                                current_line = [button_name]
                                                line_number += 1
                                        elif (previous_results[-3:] == ["player", "banker", "player"] or
                                        previous_results[-3:] == ["banker", "player", "banker"]):
                                        # Opposite pattern for 3 results
                                            last_assumed_result = "player" if previous_results[-1] == "banker" else "banker"
                                            print("Detected opposite pattern for 3 results, assuming opposite:", last_assumed_result)
                                            if button_name != previous_results[-1]:
                                                game_results.append(current_line)
                                                current_line = [button_name]
                                                line_number += 1
                                            else:
                                                current_line.append(button_name)

                            current_line.append(button_name)
                            previous_results.append(button_name)

                            game_results.append(current_line)
                            print(f"Line {line_number}: {current_line}")
                            current_line = []
                            waiting_for_result = False
                            bets_open_detected = False
                            round_complete = True
                            last_change_time[button_name] = time.time()
                            print("--------------------------------------NEXT ROUND-----------------------------------------")
                            unselect_after_result()

                    prev_button_colors[button_name] = current_color

            time.sleep(0.1)

    connection.close()

# Add the unselect_after_result function to click at the unselect position after a result is detected
def unselect_after_result():
    pyautogui.moveTo(50, 950)
    pyautogui.click()  # Click to unselect the bet

# Run the betting script
run_betting_script()


