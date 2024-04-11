import os
import json
import re
import getpass

user = getpass.getuser()

base_dir = '/home/' + user + '/repositories/1_6_content'

output_dir = '/home/' + user + '/repositories/AnthroCharactersContinued/assets/Genderswaps'

names = ['Alex', 'Elliott', 'Harvey', 'Sam', 'Sebastian', 'Shane', 'Abigail', 'Abby', 'Emily', 'Haley', 'Leah', 'Maru', 'Penny', 'Sebby']

commands1 = ['addTemporaryActor', 
             'advancedMove', 
             'animate', 
             'changeName', 
             'changeYSourceRectOffset', 
             'emote', 
             'dialogue', 
             'dialogueWarpOut', 
             'invisible',
             'invisibleWarpOut',
             'extendSourceRect',
             'faceDirection',
             'friendship',
             'hideShadow',
             'ignoreCollisions',
             'jump',
             'move',
             'positionOffset',
             'proceedPosition',
             'shake',
             'showFrame',
             'speak',
             'speed',
             'splitSpeak',
             'stopAnimation',
             'stopSwimming',
             'swimming',
             'textAboveHead',
             'warp']
commands2= ['changeName',
            'changePortrait',
            'changeSprite']

directory_map = {
        'Alex': 'Alex',
        'Elliott': 'Elliott',
        'Harvey': 'Harvey',
        'Sam': 'Sam',
        'Sebastian': 'Sebastian',
        'Shane': 'Shane',
        'Abigail': 'Albert',
        'Abby': 'Albert',
        'Emily': 'Emil',
        'Haley': 'Hayden',
        'Leah': 'Liam',
        'Maru': 'Marcus',
        'Penny': 'Perry',
        'Sebby': "Sebastian"
        }

special_words = ['bed', 'beginGame', 'credits', 'dialogue', 'dialogueWarpOut', 'invisible', 'invisibleWarpOut', 'ShaneJOSH']

excluded_files = [
    '/MoviesReactions.json',
    '/Shops.json',
    '/Weddings.json',
    '/schedules/',
    '/Characters.json',
    '/ConcessionTastes.json',
    '/TriggerActions.json',
    '/credits.json'
]

def save(file_path, json_path, new_text):
    for name in names:
        if '{{' + name + '}}' in new_text:
            print(name + " in new_text")
            save_file_name = output_dir + '/' + directory_map[name] + '/dialogue_changes.json'
            data = {}
            with open(save_file_name) as f:
                data = json.load(f)
            
            action = "EditData"
            target = file_path.split('.')[0]
            target_field = json_path.copy()
            entry_key = target_field.pop()
            added_to_existing = False
            for entry in data['Changes']:
                if entry['Target'] == target and not entry.get('When') and target_field == entry.get("TargetField", []):
                    added_to_existing = True
                    existing_entries = entry['Entries']
                    if not existing_entries.get(entry_key):
                        existing_entries[entry_key] = new_text
                    break
            if not added_to_existing:
                new_entry = {
                        "Action": action,
                        "Target": target,
                        "Entries": {
                            entry_key: new_text
                            }
                        }
                if target_field:
                    new_entry["TargetField"] = target_field
                data['Changes'].append(new_entry)
            with open(save_file_name, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)

def full_in(word, string):
    if re.search(r"\b"+re.escape(word)+r"\b", string):
        return True
    return False

def is_float(word):
    try:
        float(word)
        return True
    except ValueError:
        return False

def replace_names(line):
    split_line = line.split(" ")
    pause = 0
    new_line = []
    for word in split_line:
        # Catch an edge case
        if '(O)' in word and new_line:
            new_line[-1] = new_line[-1].replace('{', '')
            new_line[-1] = new_line[-1].replace('}', '')
        if is_float(word) and new_line:
            new_line[-1] = new_line[-1].replace('{', '')
            new_line[-1] = new_line[-1].replace('}', '')
        # Replace names
        if pause < 1 and not ('revealtaste' in word):
            for name in names:
                word = re.sub(r'\b' + name + r'\b', r'{{' + name + r'}}', word)
        pause = pause - 1
        # Skip next names if commands are seen
        for command in commands1:
            if full_in(command, word):
                pause = 1
        for command in commands2:
            if full_in(command, word):
                pause = 2
        new_line.append(word)
    return " ".join(new_line)

def valid_file(file_path):
    for excluded_file in excluded_files:
        if excluded_file in file_path:
            return False
    return True
        
def search_for_files(root_dir):
    for root, dirs, files in os.walk(root_dir):
        for file_name in files:
            if file_name.endswith('.json'):
                file_path = os.path.join(root, file_name)
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    find_text_in_json(data, file_path, [])

def find_text_in_json(data, file_path, path=[]):
    if isinstance(data, dict):
        for key, value in data.items():
            path.append(key)
            if isinstance(value, (dict, list)):
                find_text_in_json(value, file_path, path)
            elif isinstance(value, str):
                replaced_value = replace_names(value)
                if value != replaced_value and valid_file(file_path):
                    relative_path = os.path.relpath(file_path, start=base_dir)
                    json_path = path.copy()
                    print("Changed text at location: ", relative_path)
                    print("Path within JSON: ", '.'.join(path))
                    print("Old text: ", value)
                    print("New text: ", replaced_value)
                    print("")
                    save(relative_path, json_path, replaced_value)
            path.pop()
    elif isinstance(data, list):
        for index, item in enumerate(data):
            path.append('#' + str(index))
            if isinstance(item, (dict, list)):
                find_text_in_json(item, file_path, path)
            elif isinstance(item, str):
                replaced_value = replace_names(item)
                if item != replaced_value and valid_file(file_path):
                    relative_path = os.path.relpath(file_path, start=base_dir)
                    json_path = path.copy()
                    print("Changed text at location: ", relative_path)
                    print("Path within JSON: ", '.'.join(path))
                    print("Old text: ", item)
                    print("New text: ", replaced_value)
                    print("")
                    save(relative_path, json_path, replaced_value)
            path.pop()

# Example usage:
search_for_files(base_dir)
