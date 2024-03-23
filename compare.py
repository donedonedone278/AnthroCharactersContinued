import os
import shutil
import subprocess

def compare_directories(dir1, dir2, output_dir):
    # Create the output directory if it doesn't exist
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Iterate over items in both directories
    for item in os.listdir(dir1):
        item_path1 = os.path.join(dir1, item)
        item_path2 = os.path.join(dir2, item)
        output_item_path = os.path.join(output_dir, item)

        # If both are directories, recursively compare
        if os.path.isdir(item_path1) and os.path.isdir(item_path2):
            compare_directories(item_path1, item_path2, output_item_path)
        # If both are files, compare using diffimg
        elif os.path.isfile(item_path1) and os.path.isfile(item_path2):
            if item.endswith('.png'):
                print(item_path1)
                print(item_path2)
                print(output_item_path)
                result = subprocess.run(['convert', item_path1, item_path2, '-fuzz', '15%', '-compose', 'ChangeMask', '-composite', output_item_path], capture_output=True)
                if result.returncode != 0:
                    print(f"Differences found in file: {item}")
                else:
                    print(f"fdsafdsa: {item}")
        # If items have different types, copy both to output directory
        else:
            shutil.copy2(item_path1, output_item_path)
            shutil.copy2(item_path2, output_item_path)
            print(f"Differences found in item types: {item}")

if __name__ == "__main__":
    # Replace these paths with the paths to your directories
    directory1 = '/home/sorsenl/repositories/changed_content_furry'
    directory2 = '/home/sorsenl/repositories/changed_content_1_5'
    output_directory = '/home/sorsenl/repositories/just_furry'

    compare_directories(directory1, directory2, output_directory)

# convert item_path1 item_path2 -fuzz 15% -compose ChangeMask -composite output_item_path