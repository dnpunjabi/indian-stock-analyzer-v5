with open('backend/static/app.js', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Truncate at }; at line 59781
clean_lines = []
for line in lines:
    clean_lines.append(line)
    if '}, 120);' in line:
        clean_lines.append('};\n')
        break

with open('backend/static/app.js', 'w', encoding='utf-8') as f:
    f.writelines(clean_lines)

print("Cleaned up app.js tail successfully.")
