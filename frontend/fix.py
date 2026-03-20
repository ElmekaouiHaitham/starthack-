import sys
import os

filepath = 'src/components/OutputPanel.tsx'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

replacements = {
    'â€”': '—',
    'Â·': '·',
    'â–¼': '▼',
    # Deprecated: UI now uses inline SVG icons (no emoji glyphs).
    'âœ“': '[CHECK]',
    'âœ—': '[CROSS]',
    'âš¡': '[BOLT]',
    'â†’': '→',
    'â† ': '←',
    'âŠ™': '[TARGET]',
    'ðŸ”´': '[RED]',
    'ðŸŸ¡': '[AMBER]',
    'ðŸŸ¢': '[GREEN]',
    'Ã¢â€Â': '←'
}

for bad, good in replacements.items():
    text = text.replace(bad, good)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(text)
print("Done fixing encoding!")
