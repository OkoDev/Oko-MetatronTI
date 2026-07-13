"""Fix TASKS.md formatting: close brackets, fix broken links."""
import re

TASKS = "TASKS.md"
with open(TASKS, "r", encoding="utf-8") as f:
    content = f.read()

fixes = 0

# 1. Fix [[wikilinks]] → text
content, n = re.subn(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', r'\1', content)
print(f"[[wikilinks]]: {n}"); fixes += n

# 2. Fix unclosed ** in table cells — close the pair
lines = content.split('\n')
out = []
for line in lines:
    if line.strip().startswith('|') and line.count('**') % 2 != 0:
        # Find last ** and close it
        parts = line.rsplit('**', 1)
        if len(parts) == 2:
            # If the part after ** doesn't have a matching **, remove the stray **
            if '**' not in parts[1]:
                line = parts[0] + parts[1]
                fixes += 1
    out.append(line)
content = '\n'.join(out)
print(f"Unclosed **: fixed")

# 3. Fix missing ) in markdown links: [text](#anchor without )
content, n = re.subn(r'\[([^\]]+)\]\(#([a-zA-Z0-9_-]+)(?=\s|\||$)', r'[\1](#\2)', content)
print(f"Missing ) links: {n}"); fixes += n

# 4. Balance parentheses per line
lines = content.split('\n')
out = []
for line in lines:
    if line.strip().startswith('|'):
        diff = line.count('(') - line.count(')')
        if diff > 0:
            line = line + ')' * diff
            fixes += 1
        diff = line.count('[') - line.count(']')
        if diff > 0:
            line = line + ']' * diff
            fixes += 1
    out.append(line)
content = '\n'.join(out)

with open(TASKS, "w", encoding="utf-8") as f:
    f.write(content)

print(f"Total fixes: {fixes}")
