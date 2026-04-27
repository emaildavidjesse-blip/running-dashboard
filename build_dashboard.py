#!/usr/bin/env python3
import json

def main():
    with open('runs_data.json') as f:
        data = json.load(f)

    with open('template.html') as f:
        template = f.read()

    output = template.replace(
        'const RUNS_DATA_PLACEHOLDER = null;',
        f'const RUNS = {json.dumps(data)};',
    )

    with open('index.html', 'w') as f:
        f.write(output)

    run_total = sum(len(data[y]) for y in data if y.isdigit())
    print(
        f'Built index.html — '
        f'{run_total} runs, '
        f'{len(data.get("vo2max", []))} VO2max, '
        f'{len(data.get("rhr", []))} RHR, '
        f'{len(data.get("bodyBattery", []))} BB readings'
    )

if __name__ == '__main__':
    main()
