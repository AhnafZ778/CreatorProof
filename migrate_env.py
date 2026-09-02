import os
import json

env_file = '/home/ahnaf-zakaria/Desktop/BCOL/creatorproof/apps/api/.env'

with open(env_file, 'r') as f:
    lines = f.readlines()

updated_lines = []
for line in lines:
    if line.startswith('CREATORPROOF_JOB_BACKEND='):
        updated_lines.append('CREATORPROOF_JOB_BACKEND=local\n')
    elif line.startswith('CREATORPROOF_LOCAL_JOB_WORKERS='):
        pass # Handle this at the end if not found
    elif line.startswith('CREATORPROOF_SYNTHETIC_EXTERNAL_TIMEOUT_SECONDS='):
        updated_lines.append('CREATORPROOF_SYNTHETIC_EXTERNAL_TIMEOUT_SECONDS=120\n')
    elif line.startswith('CREATORPROOF_VISIBLE_AI_MARKER_TIMEOUT_SECONDS='):
        updated_lines.append('CREATORPROOF_VISIBLE_AI_MARKER_TIMEOUT_SECONDS=12\n')
    elif line.startswith('CREATORPROOF_SYNTHETIC_EXTERNAL_DETECTORS_JSON='):
        try:
            # Parse the JSON if it's there
            val = line.split('=', 1)[1].strip()
            if val.startswith('['):
                detectors = json.loads(val)
                for d in detectors:
                    if d.get('name') == 'grip-clipdet':
                        # Update the command to use {manifest}
                        d['command'] = "python -m scripts.clipdet_json_adapter --manifest {manifest} --repo ./vendor/ClipBased-SyntheticImageDetection --weights ./vendor/ClipBased-SyntheticImageDetection/weights --runner-python ./vendor/ClipBased-SyntheticImageDetection/.venv/bin/python --device cpu"
                        # We don't overwrite evidence_family and source_scope, keep them as is
                updated_lines.append(f"CREATORPROOF_SYNTHETIC_EXTERNAL_DETECTORS_JSON={json.dumps(detectors)}\n")
            else:
                updated_lines.append(line)
        except Exception as e:
            updated_lines.append(line)
    else:
        updated_lines.append(line)

# Ensure CREATORPROOF_LOCAL_JOB_WORKERS is in the file
if not any(l.startswith('CREATORPROOF_LOCAL_JOB_WORKERS=') for l in updated_lines):
    # Insert it after CREATORPROOF_JOB_BACKEND
    for i, line in enumerate(updated_lines):
        if line.startswith('CREATORPROOF_JOB_BACKEND='):
            updated_lines.insert(i+1, 'CREATORPROOF_LOCAL_JOB_WORKERS=1\n')
            break

with open(env_file, 'w') as f:
    f.writelines(updated_lines)

print("Environment migration complete.")
