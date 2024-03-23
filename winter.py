import json
import shutil

# Read the JSON file
with open('content.json', 'r') as file:
    data = json.load(file)

# Get the array of dictionaries under "Changes"
changes = data.get('Changes', [])

# Iterate through each dictionary
for change in changes:
    # Check if the dictionary contains "FromFile" key
    if 'FromFile' in change:
        # Check if the "FromFile" string contains "_Winter"
        if '_Winter.png' in change['FromFile']:
            print(change['FromFile'])
            #old_filename = change['FromFile'].replace('_Winter', '')

            #shutil.copyfile(old_filename, change['FromFile'])