#!/usr/bin/env python3

import os
import re
import time
import yaml
import argparse


SLEEP_TIME = 0.2
PROMPT_ROLES = ['system', 'user', 'assistant']
DEFAULT_CHARCARD_TEMPLATE = """{{description}}
{{personality}}
{% if scenario %}
Scenario: {{scenario}}
{% endif %}
{% if message_examples %}
EXAMPLE MESSAGES:
{% for message in message_examples %}
{{name}}: {{message}}
{% endfor %}
{% endif %}
"""
DEFAULT_SETTINGS = {
    'active': True,
    'user': 'user',
    'api_mode': 'openai-chat',
    'prefix_messages_with_name': False,
    'add_final_message_padding': True,
    'guess_next_speaker': True,
    'enforce_nonrepeating_roles': False,
    'postfix_output_with_user': True,
    'chat_template_vars': {},
    'api_call_headers': {},
    'api_call_props': {},
    'charcard_template': DEFAULT_CHARCARD_TEMPLATE,
    'character_book_png': None,
}


def find_dot_config_file(base_path, filename):
    current_dir = base_path
    home_dir = os.path.expanduser("~")
    home_dir = os.path.abspath(home_dir)
    while True:
        config_path = os.path.join(current_dir, filename)
        if os.path.isfile(config_path):
            return config_path

        if os.path.abspath(current_dir) == home_dir:
            return None

        parent_dir = os.path.dirname(current_dir)
        if parent_dir == current_dir:
            return None

        current_dir = parent_dir


def parse_chathistory(history_text):
    history = []

    assert(not history_text or history_text.startswith('@'))
    parts = re.split(r'^@(.*)', history_text, flags=re.MULTILINE)
    parts.pop(0)

    for i in range(0, len(parts), 2):
        message = {'name': parts[i]}
        message['content'] = parts[i + 1]
        history.append(message)

    return history


def watch_and_do(path):
    last_modified = os.path.getmtime(path)

    while True:
        current_modified = os.path.getmtime(path)
        if current_modified != last_modified:
            yield(path)
            last_modified = os.path.getmtime(path)
        time.sleep(SLEEP_TIME)


def parse_data_and_chathistory(text):
    assert(text.startswith('---'))
    parts = text.split('---\n', 2)
    assert(len(parts) == 3)
    data = yaml.safe_load(parts[1])
    history = parse_chathistory(parts[2])
    return(data, history)


def render_template(template, user):
    if user:
        processed_template = template.replace("{{user}}", user)
    return processed_template


def roleplays_to_markdown(history):
    ret = ''

    for message in history:
        ret += f'### {message['name']}\n'
        ret += message['content']
        ret += '\n\n'

    return ret


def handle_updated_prompt(path):
    base_path = os.path.dirname(path)

    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    config_content, history = parse_data_and_chathistory(content)

    # Merge default config, user config, and .chathistory config .
    config_file_path = find_dot_config_file(base_path, '.chathistory')
    if config_file_path:
        with open(config_file_path) as f:
            config_file = yaml.safe_load(f)

    config_tmp = config_file.copy()
    config_tmp.update(config_content)
    if config_tmp.get('profile'):
        config_profile = config_tmp['profiles'][config_tmp['profile']]

    config = DEFAULT_SETTINGS.copy()
    config.update(config_file)
    config.update(config_profile)
    config.update(config_content)

    user = config['user']

    # Render chathistory templates.
    for x in history:
        x['content'] = render_template(x['content'], user)
        x['content'] = x['content'].strip('\n')

    markdown = roleplays_to_markdown(history)
    with open('_markdown.md', 'w') as f:
        f.write(markdown)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('path', nargs='?')
    parser.add_argument('-w', '--watch')
    args = parser.parse_args()

    if args.watch is not None:
        assert(args.path is None)
        for path in watch_and_do(args.watch):
            handle_updated_prompt(path)

    if args.path is not None:
        assert(args.watch is None)
        handle_updated_prompt(args.path)


if __name__ == "__main__":
    main()
