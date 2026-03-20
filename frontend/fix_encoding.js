const fs = require('fs');
const path = require('path');

const file = process.argv[2];
let text = fs.readFileSync(file, 'utf8');

// The file was likely saved by accidentally interpreting utf8 bytes as windows-1252.
// Let's replace the known sequences:
const replacements = {
  'â€”': '—',
  'Â·': '·',
  'â–¼': '▼',
  // Deprecated: UI now uses inline SVG icons (no emoji glyphs).
  'âœ“': '[CHECK]',
  'âœ—': '[CROSS]',
  'âš¡': '[BOLT]',
  'â†’': '→',
  'â† ': '←',
  'âŠ™': '[TARGET]',
  'ðŸ”´': '[RED]',
  'ðŸŸ¡': '[AMBER]',
  'ðŸŸ¢': '[GREEN]',
  'â€"': '—',
};

for (const [bad, good] of Object.entries(replacements)) {
  text = text.split(bad).join(good);
}

fs.writeFileSync(file, text, 'utf8');
console.log('Fixed encoding in', file);
