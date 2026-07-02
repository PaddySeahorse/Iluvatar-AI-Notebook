const vm = require('vm');
const fs = require('fs');

const lines = fs.readFileSync('/workspace/static/js/state.js', 'utf8').split('\n');

for (let i = 1; i <= lines.length; i += 10) {
    const chunk = lines.slice(0, i).join('\n');
    try {
        new vm.SourceTextModule(chunk);
        console.log(`Lines 1-${i}: OK`);
    } catch (e) {
        if (e.message.includes('missing ) after argument list')) {
            console.log(`Lines 1-${i}: ERROR -> missing ) after argument list`);
            // Narrow down in this chunk
            for (let j = Math.max(1, i - 9); j <= i; j++) {
                const sub = lines.slice(0, j).join('\n');
                try {
                    new vm.SourceTextModule(sub);
                    console.log(`  Lines 1-${j}: OK`);
                } catch (subErr) {
                    if (subErr.message.includes('missing ) after argument list')) {
                        console.log(`  Lines 1-${j}: ERROR -> missing ) after argument list`);
                        console.log(`  Problem likely around line ${j}:`);
                        for (let k = Math.max(0, j - 3); k < Math.min(lines.length, j + 2); k++) {
                            console.log(`    ${k + 1}: ${lines[k]}`);
                        }
                        process.exit(0);
                    } else if (subErr.message.includes('Unexpected end of input')) {
                        console.log(`  Lines 1-${j}: Unexpected end of input (incomplete structure)`);
                    } else {
                        console.log(`  Lines 1-${j}: OTHER -> ${subErr.message}`);
                    }
                }
            }
            process.exit(0);
        } else if (e.message.includes('Unexpected end of input')) {
            console.log(`Lines 1-${i}: Unexpected end of input (incomplete structure)`);
        } else {
            console.log(`Lines 1-${i}: OTHER -> ${e.message}`);
        }
    }
}
