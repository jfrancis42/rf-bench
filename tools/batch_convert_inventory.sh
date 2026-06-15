#!/bin/bash
# Batch convert rf-bench projects to use inventory system
# Safe: creates .backup files before modifying

set -e

PROJECTS_DIR=~/Dropbox/build/rf-bench/projects

echo "Converting projects to use inventory system..."
echo "Backup files will be created as *.backup"
echo ""

# Count files to convert
total=$(find "$PROJECTS_DIR" -name "*.py" -type f | wc -l)
echo "Found $total Python files"
echo ""

converted=0

for file in $(find "$PROJECTS_DIR" -name "*.py" -type f | sort); do
    # Skip if already converted
    if grep -q "from rf_bench import connect" "$file" 2>/dev/null; then
        continue
    fi

    # Skip if doesn't use target instruments
    if ! grep -qE "(SSA3000X|SDG1000X|SDS2000X|SDM3000X|SPD3303X|IC7300|IC9700|FT891)" "$file"; then
        continue
    fi

    # Create backup
    cp "$file" "$file.backup"

    # Perform replacements
    modified=false

    # 1. Replace hardcoded IP defaults
    if sed -i 's/DEFAULT_SSA_HOST\s*=\s*"10\.1\.1\.60"/DEFAULT_SSA_HOST = None  # Now uses inventory/g' "$file" 2>/dev/null; then
        modified=true
    fi
    if sed -i 's/DEFAULT_SDG_HOST\s*=\s*"10\.1\.1\.55"/DEFAULT_SDG_HOST = None  # Now uses inventory/g' "$file" 2>/dev/null; then
        modified=true
    fi
    if sed -i 's/DEFAULT_SDS_HOST\s*=\s*"10\.1\.1\.58"/DEFAULT_SDS_HOST = None  # Now uses inventory/g' "$file" 2>/dev/null; then
        modified=true
    fi
    if sed -i 's/DEFAULT_SDM_HOST\s*=\s*"10\.1\.1\.63"/DEFAULT_SDM_HOST = None  # Now uses inventory/g' "$file" 2>/dev/null; then
        modified=true
    fi
    if sed -i 's/DEFAULT_SPD_HOST\s*=\s*"10\.1\.1\.56"/DEFAULT_SPD_HOST = None  # Now uses inventory/g' "$file" 2>/dev/null; then
        modified=true
    fi

    # 2. Add inventory import after last rf_bench import
    if grep -q "from rf_bench\." "$file" && ! grep -q "from rf_bench import connect" "$file"; then
        # Find last rf_bench import line and add inventory import after it
        lastline=$(grep -n "from rf_bench\." "$file" | tail -1 | cut -d: -f1)
        if [ -n "$lastline" ]; then
            sed -i "${lastline}a from rf_bench import connect" "$file"
            modified=true
        fi
    fi

    if $modified; then
        ((converted++))
        echo "[$converted] Converted: $file"
    else
        # No changes, remove backup
        rm "$file.backup"
    fi
done

echo ""
echo "Converted $converted files"
echo "Backup files saved as *.backup"
echo ""
echo "Next steps:"
echo "1. Review changes: diff file.backup file"
echo "2. Update connection code manually (grep for 'SSA3000X(' etc.)"
echo "3. Test converted scripts"
echo "4. Remove backups: find $PROJECTS_DIR -name '*.backup' -delete"
