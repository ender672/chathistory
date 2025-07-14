#!/usr/bin/env python3

import sys
import base64
import json
import PIL.Image


def extract_ai_card_data(png_path):
    png_file = open(png_path, "rb")
    img = PIL.Image.open(png_file)
    img.load()

    chara = img.info.get("ccv3")
    if not chara:
        chara = img.info.get("chara")
    decoded_data = base64.b64decode(chara).decode("utf-8")
    data = json.loads(decoded_data)
    return data['data']


if __name__ == "__main__":
    card_file = sys.argv[1]
    ai_card_data = extract_ai_card_data(card_file)
    print(json.dumps(ai_card_data, indent=2))
