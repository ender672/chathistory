#!/usr/bin/env python3

import sys
import base64
import json
import PIL.Image


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


def create_chatml_prompt(character_data):
    content_entries = []
    for entry in character_data['character_book']['entries']:
        if entry['content']:
            content_entries.append(entry['content'])
    out = "\n\n".join(content_entries)
    return out


if __name__ == "__main__":
    card_file = sys.argv[1]
    ai_card_data = extract_ai_card_data(card_file)
    chatml = create_chatml_prompt(ai_card_data)
    print(chatml)
