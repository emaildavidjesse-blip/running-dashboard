#!/usr/bin/env python3
import json

def main():
    with open('runs_data.json') as f:
        runs_data = json.load(f)

    with open('template.html') as f:
        template = f.read()

    json_str = json.dumps(runs_data)
    output = template.replace(
        'const RUNS_DATA_PLACEHOLDER = null;',
        f'const RUNS = {json_str};',
    )

    with open('index.html', 'w') as f:
        f.write(output)

    total = sum(len(v) for v in runs_data.values())
    print(f'Built index.html with {total} runs')

if __name__ == '__main__':
    main()
