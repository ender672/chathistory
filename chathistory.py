#!/usr/bin/env python3

import os
import sys
import json
import re
import time
import yaml
import base64
import urllib.request
import argparse
import datetime

import PIL.Image
import jinja2
import jinja2.sandbox
import jinja2.ext

# import http.client
# http.client.HTTPConnection.debuglevel = 1

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
    'system_prompt_file': 'sys-prompt.txt',
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


def generate_api_data_lines(req):
    try:
        resp = urllib.request.urlopen(req)
    except Exception as e:
        breakpoint()
        print('hi', file=sys.stderr)
    full_log = open("_response.json", "wb")
    for line_binary in resp:
        full_log.write(line_binary)
        line = line_binary.decode("utf-8").strip()
        if not line:
            continue
        if line == ': keep-alive':
            continue
        assert(line.startswith("data: "))
        yield json.loads(line[6:])
    full_log.close()


def generate_openai_choices(req):
    for json_data in generate_api_data_lines(req):
        assert(len(json_data['choices']) == 1)
        choice = json_data["choices"][0]
        yield choice
        if choice.get('finish_reason') in ('stop', 'length'):
            break


def process_and_log_generator(input_generator, tuple_index, filename):
    with open(filename, 'w') as f:
        for item_tuple in input_generator:
            item_to_process = item_tuple[tuple_index]
            if item_to_process is not None:
                f.write(item_to_process)
                f.flush()
            yield item_tuple


def buffer_whitespace(generator):
    in_buffer = ''

    for text in generator:
        in_buffer += text

        match = re.match(r'(.*?)(\s+)$', in_buffer)
        if match:
            if match.group(1):
                yield match.group(1)
            in_buffer = match.group(2)
            continue

        yield in_buffer
        in_buffer = ''

    if in_buffer:
        yield in_buffer


def format_as_roleplay(generator, names):
    in_buffer = ''
    is_new_speaker = True

    for text in generator:
        in_buffer += text
        remainder = ''
        out_buffer = ''

        for line in get_lines(in_buffer):
            name_match = re.match(r'^(.+): ?', line)
            if name_match:
                possible_name = name_match.group(1)
                if possible_name in names:
                    out_buffer += f'@{possible_name}\n'
                    line = line[name_match.end():]
                    is_new_speaker = True
                    if not line:
                        continue

            if is_new_speaker:
                line = line.lstrip()
                is_new_speaker = False

            if line.endswith('\n'):
                out_buffer += line
            else:
                remainder = line

        if remainder:
            might_be_name = any(x.startswith(line) for x in names)
            if not might_be_name:
                out_buffer += line
                remainder = ''

        in_buffer = remainder
        if out_buffer:
            yield out_buffer

    if in_buffer:
        yield in_buffer


def clean_whitespace(generator):
    for text in generator:
        # Remove pesky spaces before newlines.
        text = re.sub(r'[ ]+\n', '\n', text)
        # Make sure a line starting with '@' always has two newlines before it.
        text = re.sub(r'([^\n])\n@', '\1\n\n@', text)
        # Make sure we have two newlines before a line starting with a '@'.
        text = re.sub(r'^\n@', '\n\n@', text)
        yield text


def parse_chathistory(history_text):
    history = []

    if not history_text:
        return history

    if not history_text.startswith('@'):
        return [{'name': 'user', 'content': history_text}]

    parts = re.split(r'^@(.*)', history_text, flags=re.MULTILINE)
    parts.pop(0)

    for i in range(0, len(parts), 2):
        message = {'name': parts[i]}
        message['content'] = parts[i + 1]
        history.append(message)

    return history


def build_name_map(prompt_roles, user_name):
    ret = { x: x for x in prompt_roles }
    ret[user_name] = 'user'
    return ret


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


def combine_repeat_message_roles(messages):
    ret = []

    prev_prompt_role = None
    for message in messages:
        role = message['role']

        if role == prev_prompt_role:
            ret[-1]['content'] += f'\n{message['content']}'
        else:
            ret.append(message)

        prev_prompt_role = role

    return ret


def prefix_roleplays_with_name(roleplays, exception_names):
    for roleplay in roleplays:
        name = roleplay['name']
        content = roleplay['content']
        if name not in exception_names:
            roleplay['content'] = f'{name}:'
            if content:
                roleplay['content'] += f' {content}'


def roleplays_to_messages(roleplays, name_to_role_mapping):
    messages = []

    for roleplay in roleplays:
        role = name_to_role_mapping.get(roleplay['name'], 'assistant')
        messages.append({'role': role, 'content': roleplay['content']})

    return messages


def guess_next_speaker(history, user_name):
    if not history:
        return None

    last_speaker = history[-1]['name']
    last_content = history[-1]['content']

    if last_content.strip('\n') == '':
        return None

    if last_content.endswith(' '):
        return None

    for message in reversed(history):
        if message['name'] not in PROMPT_ROLES + [user_name, last_speaker]:
            return message['name']

    if last_speaker != user_name:
        return user_name

    return 'assistant'


def get_name_autocomplete(history, extra_names):
    if not history:
        return None

    # Autocomplete only works if the last message is empty. No newline.
    if history[-1]['content'] != "":
        return None

    name_candidates = [x['name'] for x in reversed(history)]
    latest_speaker = name_candidates.pop(0)

    # First, see if we have an exact name match in our history.
    for candidate in name_candidates:
        if latest_speaker == candidate:
            return None

    # Try to find a partial match, including extra names
    augmented_candidates = name_candidates + extra_names
    for candidate in augmented_candidates:
        if candidate.startswith(latest_speaker):
            return candidate[len(latest_speaker):]

    return None


def get_final_message_padding(message):
    # If the final message is an empty string, we need a newline after the name.
    if message == '':
        return '\n'

    # If the final message is a single newline, it's empty and ready to be
    # filled.
    if message == '\n':
        return None

    # If the final message ends with a space, we want to continue from there.
    if message.endswith(' '):
        return None

    # If the final message is none of the above and ends with two newlines,
    # we are ready for the next, unknown speaker.
    if message.endswith('\n\n'):
        return None

    # If the final message is none of the above and ends with a single newline,
    # add an extra newline and we're ready for the next, unknown speaker.
    if message.endswith('\n'):
        return '\n'

    # If we get this far, the final message has content, but no newlines. We
    # need two newlines to be ready for the next, unknown speaker.
    return '\n\n'


def get_lines(input_string):
    start_index = 0
    while start_index < len(input_string):
        newline_index = input_string.find('\n', start_index)

        if newline_index == -1:
            yield input_string[start_index:]
            break
        else:
            yield input_string[start_index : newline_index + 1]
            start_index = newline_index + 1


def resolve_local_path(base_dir, path):
    assert('..' not in base_dir)
    assert('..' not in path)
    return os.path.join(base_dir, path)


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


def render_template(base_dir, template, user, charcard_template_str, chars):
    def replace_insert_txt(match):
        path = match.group(1).strip()
        resolved_path = resolve_local_path(base_dir, path)
        with open(resolved_path, 'r', encoding='utf-8') as f:
            return f.read()

    def replace_insert_png(match):
        path = match.group(1).strip()
        resolved_path = resolve_local_path(base_dir, path)

        def create_chatml_prompt(character_data):
            name = character_data.get('name', 'Character').strip()
            description = character_data.get('description')
            personality = character_data.get('personality')
            scenario = character_data.get('scenario')
            mes_example_ary = []
            mes_example = character_data.get('mes_example')
            if mes_example:
                mes_example_ary = mes_example.split('<START>')
                mes_example_ary = [x.strip() for x in mes_example_ary]
                mes_example_ary = [x for x in mes_example_ary if x]

            def strftime_now(format):
                return datetime.datetime.now().strftime(format)

            jinja_env = jinja2.sandbox.ImmutableSandboxedEnvironment(
                trim_blocks=True,
                lstrip_blocks=True,
                extensions=[jinja2.ext.loopcontrols]
            )
            jinja_env.globals["strftime_now"] = strftime_now

            template = jinja_env.from_string(charcard_template_str)
            charcard = template.render(
                name=name,
                description=description,
                personality=personality,
                scenario=scenario,
                message_examples=mes_example_ary,
            )

            charcard = charcard.replace('{{char}}', name)
            # Some charcards have windows style newlines. Replace all with unix.
            charcard = charcard.replace('\r\n', '\n')
            return charcard

        ai_card_data = extract_ai_card_data(resolved_path)
        return create_chatml_prompt(ai_card_data)

    all_char_cards = [f'{{{{insert_text chars/{x}.txt}}}}' for x in chars]
    all_char_cards = '\n\n'.join(all_char_cards)
    processed_template = re.sub(
        r"\{\{auto_insert_chars\}\}",
        all_char_cards,
        template
    )

    processed_template = re.sub(
        r"\{\{insert_text\s+(.*?)\}\}",
        replace_insert_txt,
        processed_template
    )

    processed_template = re.sub(
        r"\{\{insert_charcard_png\s+(.*?)\}\}",
        replace_insert_png,
        processed_template
    )

    if user:
        processed_template = processed_template.replace("{{user}}", user)
    return processed_template


def messages_to_chathistory(messages):
    ret = ''
    for message in messages:
        ret += f'@{message['role']}\n{message['content']}\n\n'
    return ret


def render_chat_template(chat_template_str, messages, vars):
    template = jinja2.Template(chat_template_str)

    completion_message = ''
    if messages[-1]['role'] == 'assistant':
        last_message = messages.pop(-1)
        completion_message = last_message['content']

    raw_prompt = template.render(
        messages=messages,
        add_generation_prompt=True,
        **vars,
    )
    raw_prompt += completion_message
    return raw_prompt


def generate(io_out, working_directory, config_content, history, template_directory):
    # Merge default config, user config, and .chathistory config .
    config_file_path = find_dot_config_file(working_directory, '.chathistory')
    if config_file_path:
        with open(config_file_path) as f:
            config_file = yaml.safe_load(f)

    config_tmp = config_file.copy()
    config_tmp.update(config_content)
    config_profile = {}
    if config_tmp.get('profile'):
        config_profile = config_tmp['profiles'][config_tmp['profile']]

    config = DEFAULT_SETTINGS.copy()
    config.update(config_file)
    config.update(config_profile)
    config.update(config_content)

    with open("_processed_config.yaml", "w") as f:
        yaml.dump(config, f)

    if not config['active']:
        return

    user = config['user']
    out_buf = ''

    # Append name autocomplete, newlines, and optionally a next speaker
    name_autocomplete = get_name_autocomplete(history, [user] + PROMPT_ROLES)
    if name_autocomplete:
        history[-1]['name'] += name_autocomplete
        out_buf += name_autocomplete

    if config['add_final_message_padding'] and history:
        final_padding = get_final_message_padding(history[-1]['content'])
        if final_padding:
            history[-1]['content'] += final_padding
            out_buf += final_padding

    next_speaker = guess_next_speaker(history, user)
    if config['guess_next_speaker'] and next_speaker:
        history.append({'name': next_speaker, 'content': '\n'})
        out_buf += f'@{next_speaker}\n'

    if out_buf:
        io_out.write(out_buf)
        io_out.flush()

    # Auto-add system prompt if there is one in the current directory
    if 'system_prompt_file' in config and history[0]['name'] != 'system':
        sys_prompt_path = resolve_local_path(template_directory, config['system_prompt_file'])
        if os.path.isfile(sys_prompt_path):
            with open(sys_prompt_path, 'r') as f:
                message = {'name': 'system', 'content': f.read()}
                history.insert(0, message)

    # Render chathistory templates.
    chars = [x['name'] for x in history]
    chars = list(dict.fromkeys(chars))
    chars = [x for x in chars if x not in PROMPT_ROLES]
    charcard_template = config['charcard_template']
    for x in history:
        x['content'] = render_template(template_directory, x['content'], user, charcard_template, chars)
        x['content'] = x['content'].strip('\n')

    # Add character book entry
    if config['character_book_png']:
        candidate_path = config['character_book_png']
        resolved_path = resolve_local_path(candidate_path)
        ai_card_data = extract_ai_card_data(resolved_path)
        last_message = history[-2]
        last_message_content_norm = last_message['content'].lower()
        for entry in ai_card_data['character_book']['entries']:
            entry_keyword_found = False
            for key in entry['keys']:
                if key.lower() in last_message_content_norm:
                    entry_keyword_found = True
                    break
            if entry_keyword_found:
                last_message['content'] += f"\n\n[LOREBOOK ENTRY]\n{entry['content']}\n[/LOREBOOK ENTRY]"

    # Add "character_name:" prefixes to messages if configured.
    if config['prefix_messages_with_name']:
        prefix_roleplays_with_name(history, PROMPT_ROLES)

    # Format for OpenAI compatible chat completions API
    name_to_prompt_role = build_name_map(PROMPT_ROLES, user)
    messages = roleplays_to_messages(history, name_to_prompt_role)

    # If the last message is a user message, switch it to assistant
    if config['prefix_messages_with_name'] and messages[-1]['role'] == 'user':
        messages[-1]['role'] = 'assistant'

    # Make sure we alternate between user and assistant if configured.
    if config['enforce_nonrepeating_roles']:
        messages = combine_repeat_message_roles(messages)

    # If the last message is an empty assistant message, remove it. This never
    # happens if the prefix_messages_with_name config option is true.
    if messages[-1]['role'] == 'assistant' and not messages[-1]['content']:
        messages.pop(-1)

    # DeepSeek Chat Prefix Completion, continuation property on the last message.
    if messages[-1]['role'] == 'assistant':
        messages[-1]['prefix'] = True

    # For debug purposes, write the OpenAI message array back into chathistory
    # format.
    with open("_processed_chathistory.txt", "w") as f:
        f.write(messages_to_chathistory(messages))

    print("Sending request ...", file=sys.stderr)
    data = config['api_call_props']
    api_mode = config['api_mode']

    if api_mode == 'openai-chat':
        data['messages'] = messages
        with open("_request.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        req = urllib.request.Request(
            config['api_url'],
            data=json.dumps(data).encode('utf-8'),
            headers=config['api_call_headers'],
            method="POST"
        )
        choices = generate_openai_choices(req)
        llm_gen = ((x['delta']['content'], x['delta'].get('reasoning_content')) for x in choices if 'content' in x['delta'])

    elif api_mode == 'openai-completion':
        vars = config.get('chat_template_vars', {})
        data['prompt'] = render_chat_template(config['chat_template'], messages, vars)
        data_serialized = json.dumps(data).encode('utf-8')

        with open("_request.json", "wb") as f:
            f.write(data_serialized)

        req = urllib.request.Request(
            config['api_url'],
            headers=config['api_call_headers'],
            method="POST",
            data=data_serialized,
        )
        llm_gen = ((x['text'], None) for x in generate_openai_choices(req))

    elif api_mode == 'llamacpp-completion':
        vars = config.get('chat_template_vars', {})
        data['prompt'] = render_chat_template(config['chat_template'], messages, vars)
        data_serialized = json.dumps(data).encode('utf-8')

        with open("_request.json", "wb") as f:
            f.write(data_serialized)

        req = urllib.request.Request(
            config['api_url'],
            headers=config['api_call_headers'],
            method="POST",
            data=data_serialized,
        )
        llm_gen = ((x['content'], None) for x in generate_api_data_lines(req))

    llm_gen = process_and_log_generator(llm_gen, 0, '_response.txt')
    llm_gen = process_and_log_generator(llm_gen, 1, '_thinking.txt')
    llm_gen = (x[0] for x in llm_gen)
    llm_gen = (x for x in llm_gen if x is not None)
    names = set(x['name'] for x in history)
    llm_gen = format_as_roleplay(llm_gen, names)
    llm_gen = buffer_whitespace(llm_gen)
    llm_gen = clean_whitespace(llm_gen)

    ends_with_newline = False
    for text in llm_gen:
        ends_with_newline = text.endswith('\n')
        io_out.write(text)
        io_out.flush()

    if config['postfix_output_with_user']:
        user_postfix = f'\n@{user}\n'
        if not ends_with_newline:
            user_postfix = '\n' + user_postfix
        io_out.write(user_postfix)

    print("request finished.", file=sys.stderr)


def run_with_file(path, template_directory):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    config_content, history = parse_data_and_chathistory(content)
    with open(path, 'a') as f:
        if template_directory is None:
            template_directory = os.path.dirname(path)
        generate(f, os.getcwd(), config_content, history, template_directory)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('path', nargs='?')
    parser.add_argument('-w', '--watch')
    parser.add_argument('-t', '--template-directory')
    args = parser.parse_args()

    if args.watch is not None:
        assert(args.path is None)
        for path in watch_and_do(args.watch):
            run_with_file(path, args.template_directory)

    if args.path is not None:
        assert(args.watch is None)
        run_with_file(args.path, args.template_directory)

    if args.watch is None and args.path is None:
        template_directory = args.template_directory
        if template_directory is None:
            template_directory = os.getcwd()
        all_stdin_data = sys.stdin.read()
        config_content, history = parse_data_and_chathistory(all_stdin_data)
        generate(sys.stdout, os.getcwd(), config_content, history, template_directory)

if __name__ == "__main__":
    main()
