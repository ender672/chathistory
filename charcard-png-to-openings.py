#!/usr/bin/env python3

import sys
import base64
import json
import PIL.Image
import string

def extract_ai_card_data(png_path):
    png_file = open(png_path, "rb")
    img = PIL.Image.open(png_file)
    img.load()

    if "ccv3" in img.info:
        chara = img.info["ccv3"]
    else:
        chara = img.info["chara"]

    decoded_data = base64.b64decode(chara).decode("utf-8")
    data = json.loads(decoded_data)
    return data['data']


def filename_safe_charname(name):
    whitelist = string.ascii_letters + string.digits + "_-"
    sanitized = name.replace(' ', '_')
    sanitized = "".join(c for c in sanitized if c in whitelist)
    if not sanitized or len(sanitized) > 200:
        return "unnamed"
    return sanitized


def write_message(file, char_name, message):
    file.write(message.replace('{{char}}', char_name))


def create_chatml_prompt(character_data):
    name = character_data.get('name', 'Character').strip()
    safe_name = filename_safe_charname(name)

    first_mes = character_data.get('first_mes')
    if first_mes:
        with open(f'{safe_name}-first-message.txt', 'w') as f:
            write_message(f, name, first_mes)

    alternate_greetings = character_data.get('alternate_greetings', [])
    for i, x in enumerate(alternate_greetings):
        with open(f'{safe_name}-alternate-greeting-{i + 1}.txt', 'w') as f:
            write_message(f, name, x)


if __name__ == "__main__":
    card_file = sys.argv[1]
    ai_card_data = extract_ai_card_data(card_file)
    create_chatml_prompt(ai_card_data)
