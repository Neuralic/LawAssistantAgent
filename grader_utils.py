import json
import os

RESULTS_FILE = "grading_results.json"

def write_result_to_file(result):
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r") as f:
            data = json.load(f)
    else:
        data = []

    # Ensure result is a dictionary before appending
    if isinstance(result, dict):
        data.append(result)
    else:
        print(f"Warning: Attempted to write non-dictionary result to file: {result}")
        # Optionally, you could try to parse it if it's a string that should be JSON
        try:
            parsed_result = json.loads(result)
            data.append(parsed_result)
        except (json.JSONDecodeError, TypeError):
            print(f"Error: Could not parse and write result to file: {result}")
            # If it's still not a dict or parsable JSON, you might want to log it differently

    with open(RESULTS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def read_all_results():
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r") as f:
            data = json.load(f)
        return data
    return []

