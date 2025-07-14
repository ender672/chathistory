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
    name = character_data.get('name', 'Character').strip()
    description = character_data.get('description')
    personality = character_data.get('personality')
    scenario = character_data.get('scenario')

    system_parts = []

    if description:
        system_parts.append(description)
    if personality:
        system_parts.append(personality)
    if scenario:
        system_parts.append(f"Scenario: {scenario}")

    roleplay_prompt = "\n".join(system_parts)

    mes_example = character_data.get('mes_example')
    if mes_example:
        mes_example_ary = mes_example.split('<START>')
        mes_example_ary = [x.strip() for x in mes_example_ary]
        mes_example_ary = [x for x in mes_example_ary if x]
        if mes_example_ary:
            roleplay_prompt += "\n\nEXAMPLE MESSAGES:"
        for x in mes_example_ary:
            roleplay_prompt += f"\n\n{name}: {x}"

    roleplay_prompt = roleplay_prompt.replace('{{char}}', name)
    return roleplay_prompt


if __name__ == "__main__":
    card_file = sys.argv[1]
    ai_card_data = extract_ai_card_data(card_file)
    chatml = create_chatml_prompt(ai_card_data)
    print(chatml)
