import sys

def check_css_braces(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    stack = []
    for line_num, line in enumerate(lines, 1):
        # strip comments
        clean_line = ""
        in_comment = False
        i = 0
        while i < len(line):
            if not in_comment and line[i:i+2] == '/*':
                in_comment = True
                i += 2
            elif in_comment and line[i:i+2] == '*/':
                in_comment = False
                i += 2
            elif not in_comment:
                clean_line += line[i]
                i += 1
            else:
                i += 1
                
        for char in clean_line:
            if char == '{':
                stack.append((line_num, line.strip()))
            elif char == '}':
                if not stack:
                    print(f"Extra closing brace '}}' on line {line_num}")
                else:
                    stack.pop()
                    
    if stack:
        print(f"Unclosed braces count: {len(stack)}")
        for lnum, ltxt in stack[-10:]:
            print(f"  Unclosed '{'{'}' from line {lnum}: {ltxt[:60]}")
    else:
        print("All CSS braces are perfectly balanced!")

if __name__ == '__main__':
    check_css_braces(r'c:\Users\dheer\Desktop\AI\indian-stock-analyzer - 5.0\backend\static\styles.css')
