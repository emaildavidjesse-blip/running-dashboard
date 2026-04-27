#!/usr/bin/env python3
import json

def main():
    with open('runs_data.json') as f:
        data = json.load(f)

    with open('template.html') as f:
        template = f.read()

    json_str = json.dumps(data)
    output = template.replace(
        'const RUNS_DATA_PLACEHOLDER = null;',
        f'const RUNS = {json_str};',
    )

    with open('index.html', 'w') as f:
        f.write(output)

    run_total = sum(len(data[y]) for y in data if y.isdigit())
    vo2_total = len(data.get('vo2max', []))
    print(f'Built index.html — {run_total} runs, {vo2_total} VO2max readings')

if __name__ == '__main__':
    main()
