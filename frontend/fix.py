import sys
import os

filepath = 'src/components/OutputPanel.tsx'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

replacements = {
    'â€”': '—',
    'Â·': '·',
    'â–¼': '▼',
    'âœ“': '✓',
    'âœ—': '✗',
    'âš¡': '⚡',
    'â†’': '→',
    'â† ': '←',
    'âŠ™': '⊙',
    'ðŸ”´': '🔴',
    'ðŸŸ¡': '🟡',
    'ðŸŸ¢': '🟢',
    'Ã¢â€Â': '←'
}

for bad, good in replacements.items():
    text = text.replace(bad, good)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(text)
print("Done fixing encoding!")
