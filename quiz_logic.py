import json
import os

DATA_PATH = os.path.join(os.path.dirname(__file__), 'script.json')

try:
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        QUIZ_DATA = json.load(f)
except FileNotFoundError:
    raise FileNotFoundError("'script.json' not found; ensure it is in the same directory as quiz_logic.py.")

interpretations = QUIZ_DATA['interpretations']
type_names = QUIZ_DATA['type_names']

def calculate_result(scores):
    """Calculate the final result and return (title, text)."""
    sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)

    max_score = sorted_scores[0][1]

    if all(s == max_score for _, s in sorted_scores):
        result_key = "NEUTRAL"
        result_title = interpretations[result_key]["title"]
        interpretation_text = interpretations[result_key]["text"]

    elif sorted_scores[0][1] == sorted_scores[1][1] == sorted_scores[2][1]:
        result_key = "POLY"
        result_title = interpretations[result_key]["title"]
        interpretation_text = interpretations[result_key]["text"]

    else:
        dominant_type = sorted_scores[0][0]
        second_type = sorted_scores[1][0]
        second_score = sorted_scores[1][1]

        if (max_score - second_score) <= 2:
            result_key = "MIXED"
            dominant_name = type_names[dominant_type]
            second_name = type_names[second_type]

            title_template = interpretations[result_key]["title_template"]
            result_title = title_template.format(Dominant_Type=dominant_name, Secondary_Type=second_name)

            interpretation_text = interpretations[result_key]["text"]

        else:
            result_key = dominant_type
            result_title = interpretations[dominant_type]["title"]
            interpretation_text = interpretations[result_key]["text"]

    return result_title, interpretation_text